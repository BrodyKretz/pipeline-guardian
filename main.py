import asyncio
import json
import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

import llm
from agents import monitor_agent
from agents.chaos_agent import run_chaos
from config import (
    BASELINE_DIR,
    CHAOS_MAX_SEC,
    CHAOS_MIN_SEC,
    DATA_FILE,
    DB_FILE,
    INCIDENTS_DIR,
    MONITOR_INTERVAL_SEC,
    PIPELINE_FILE,
    ROOT,
    SUMMARY_FILE,
)
from db import init_db
from restore import restore_all
from state import EventBus

bus = EventBus()
scheduler = BackgroundScheduler()

# Automation run-state. Jobs stay scheduled but no-op unless "running",
# so pause/resume is instant and never tears down the scheduler.
RUN_STATE = "running"  # running | paused | stopped
ENV_FILE = ROOT / ".env"

# Runtime-tunable agent timings (defaults = whatever config resolved at boot,
# which already honors DEMO_FAST). Editable live from the dashboard.
TIMING = {
    "monitor": MONITOR_INTERVAL_SEC,
    "chaos_min": CHAOS_MIN_SEC,
    "chaos_max": CHAOS_MAX_SEC,
}


def _has_key():
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _mode():
    return "ai" if llm.USE_REAL else "mock"


def _write_env_key(key):
    """Merge ANTHROPIC_API_KEY into .env, preserving any other lines."""
    lines, found = [], False
    if ENV_FILE.exists():
        for ln in ENV_FILE.read_text().splitlines():
            if ln.startswith("ANTHROPIC_API_KEY="):
                lines.append(f"ANTHROPIC_API_KEY={key}")
                found = True
            else:
                lines.append(ln)
    if not found:
        lines.append(f"ANTHROPIC_API_KEY={key}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


# Curated, known-good model IDs (free-text would let a typo 404 every call).
MODELS = ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]


def _status():
    return {
        "run_state": RUN_STATE,
        "mode": _mode(),
        "has_key": _has_key(),
        "timing": TIMING,
        "model": llm.MODEL,
        "model_chaos": llm.MODEL_CHAOS,
        "model_patch": llm.MODEL_PATCH,
        "models": MODELS,
        "tokens": dict(llm.TOKEN_USAGE),
    }


def _full_reset():
    """Wipe everything back to a fresh-boot state: in-memory bus, persisted
    incident files, summary, SQLite db, and the working files. Call under
    bus.lock so it can't race a healing chain."""
    bus.reset()
    llm.reset_token_usage()
    restore_all()
    for p in INCIDENTS_DIR.glob("*.json"):  # incident files + summary.json
        p.unlink(missing_ok=True)
    DB_FILE.unlink(missing_ok=True)


def _monitor_job():
    if RUN_STATE != "running":
        return
    try:
        monitor_agent.tick(bus)
    except Exception as e:  # never let a job crash the scheduler
        import traceback

        traceback.print_exc()
        bus.emit(
            "monitor",
            "system",
            "ERROR",
            f"monitor job failed: {type(e).__name__}: {e}",
        )


def _chaos_job():
    try:
        if RUN_STATE == "running":
            run_chaos(bus)
    except Exception as e:
        import traceback

        traceback.print_exc()  # full trace to server stderr
        bus.emit(
            "chaos",
            "system",
            "ERROR",
            f"chaos job failed: {type(e).__name__}: {e}",
        )
    finally:
        delay = random.randint(TIMING["chaos_min"], TIMING["chaos_max"])
        scheduler.add_job(
            _chaos_job,
            "date",
            run_date=datetime.now() + timedelta(seconds=delay),
            id="chaos",
            replace_existing=True,
        )


async def _broadcaster(queue):
    while True:
        event = await queue.get()
        dead = []
        for ws in list(bus.connections):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            bus.connections.discard(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    bus.register_loop(loop, queue)
    restore_all()
    init_db()
    task = asyncio.create_task(_broadcaster(queue))
    bus.emit("system", "system", "SYSTEM_STARTED", "Pipeline Guard online")
    if not os.getenv("PG_DISABLE_SCHEDULER"):
        scheduler.add_job(
            _monitor_job,
            "interval",
            seconds=TIMING["monitor"],
            id="monitor",
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            _chaos_job,
            "date",
            run_date=datetime.now()
            + timedelta(
                seconds=random.randint(TIMING["chaos_min"], TIMING["chaos_max"])
            ),
            id="chaos",
        )
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/")
def dashboard():
    return FileResponse(ROOT / "dashboard" / "index.html")


@app.get("/api/state")
def api_state():
    return JSONResponse(
        {
            "incident": bus.incident,
            "events": bus.recent_events(50),
            **_status(),
        }
    )


@app.post("/api/control/{action}")
def api_control(action: str):
    global RUN_STATE
    if action == "start":
        RUN_STATE = "running"
        bus.emit("system", "system", "AUTOMATION_STARTED", "Automation running")
    elif action == "pause":
        # Toggle: clicking pause again resumes.
        if RUN_STATE == "paused":
            RUN_STATE = "running"
            bus.emit("system", "system", "AUTOMATION_STARTED", "Automation resumed")
        else:
            RUN_STATE = "paused"
            bus.emit("system", "system", "AUTOMATION_PAUSED", "Automation paused")
    elif action == "stop":
        with bus.lock:
            RUN_STATE = "stopped"
            _full_reset()
        bus.emit(
            "system",
            "system",
            "SYSTEM_RESET",
            "Stopped and fully reset to initial state",
        )
    else:
        return JSONResponse({"error": f"unknown action {action}"}, status_code=400)
    return JSONResponse(_status())


class ModeReq(BaseModel):
    mode: str
    key: str | None = None


@app.post("/api/mode")
def api_mode(req: ModeReq):
    if req.mode == "mock":
        llm.USE_REAL = False
        bus.emit("system", "system", "MODE_CHANGED", "Switched to MOCK brain")
        return JSONResponse(_status())
    # mode == "ai"
    if req.key and req.key.strip():
        key = req.key.strip()
        _write_env_key(key)
        os.environ["ANTHROPIC_API_KEY"] = key
    if not _has_key():
        return JSONResponse({"needs_key": True, **_status()})
    llm.USE_REAL = True
    bus.emit("system", "system", "MODE_CHANGED", "Switched to AI (Claude) brain")
    return JSONResponse(_status())


class TimingReq(BaseModel):
    monitor: int
    chaos_min: int
    chaos_max: int


@app.post("/api/timing")
def api_timing(req: TimingReq):
    if req.monitor < 1 or req.chaos_min < 1:
        return JSONResponse(
            {"error": "intervals must be >= 1 second", **_status()},
            status_code=400,
        )
    if req.chaos_min > req.chaos_max:
        return JSONResponse(
            {"error": "chaos_min must be <= chaos_max", **_status()},
            status_code=400,
        )
    TIMING.update(
        monitor=req.monitor,
        chaos_min=req.chaos_min,
        chaos_max=req.chaos_max,
    )
    # Apply live: reschedule the monitor interval and the pending chaos run.
    if scheduler.running:
        try:
            scheduler.reschedule_job(
                "monitor", trigger="interval", seconds=TIMING["monitor"]
            )
            scheduler.add_job(
                _chaos_job,
                "date",
                run_date=datetime.now()
                + timedelta(
                    seconds=random.randint(
                        TIMING["chaos_min"], TIMING["chaos_max"]
                    )
                ),
                id="chaos",
                replace_existing=True,
            )
        except Exception as e:
            bus.emit("system", "system", "ERROR", f"reschedule failed: {e}")
    bus.emit(
        "system",
        "system",
        "TIMING_CHANGED",
        f"Monitor every {TIMING['monitor']}s · "
        f"Chaos every {TIMING['chaos_min']}–{TIMING['chaos_max']}s",
        dict(TIMING),
    )
    return JSONResponse(_status())


class ModelReq(BaseModel):
    model: str
    agent: str = "default"  # "default" | "chaos" | "patch"


@app.post("/api/model")
def api_model(req: ModelReq):
    if req.model not in MODELS:
        return JSONResponse(
            {"error": f"unknown model {req.model}", **_status()},
            status_code=400,
        )
    if req.agent == "chaos":
        llm.MODEL_CHAOS = req.model
        label = f"chaos model -> {req.model}"
    elif req.agent == "patch":
        llm.MODEL_PATCH = req.model
        label = f"patch model -> {req.model}"
    else:
        llm.MODEL = req.model
        label = f"default model -> {req.model}"
    bus.emit("system", "system", "MODEL_CHANGED", label)
    return JSONResponse(_status())


@app.get("/api/incidents")
def api_incidents():
    summary = {"resolved": {}, "escalated": {}}
    if SUMMARY_FILE.exists():
        try:
            summary = json.loads(SUMMARY_FILE.read_text())
        except json.JSONDecodeError:
            pass
    files = sorted(
        (p for p in INCIDENTS_DIR.glob("*.json") if p.name != "summary.json"),
        reverse=True,
    )[:10]
    recent = [json.loads(p.read_text()) for p in files]
    return JSONResponse({"summary": summary, "recent": recent})


CHAOS_CATEGORIES = [
    "random", "schema_drift", "type_drift", "format_drift", "encoding_drift",
    "bad_sensor", "volume_drift", "unit_drift", "structural_drift",
]


class ChaosReq(BaseModel):
    category: str = "random"


@app.post("/api/chaos/trigger")
def api_chaos_trigger(req: ChaosReq = ChaosReq()):
    """Fire chaos immediately, regardless of automation state. Runs in a
    one-shot scheduler job so HTTP doesn't block on the AI tool loop."""
    if req.category not in CHAOS_CATEGORIES:
        return JSONResponse(
            {"ok": False, "reason": f"unknown category: {req.category}"},
            status_code=400,
        )
    if bus.incident["active"]:
        return JSONResponse(
            {"ok": False, "reason": "incident already active"}, status_code=409
        )
    if not scheduler.running:
        return JSONResponse(
            {"ok": False, "reason": "scheduler not running"}, status_code=503
        )
    cat = None if req.category == "random" else req.category
    scheduler.add_job(
        lambda: run_chaos(bus, category=cat),
        "date",
        run_date=datetime.now(),
        id="chaos_manual",
        replace_existing=True,
    )
    return JSONResponse({"ok": True, "category": req.category})


@app.get("/api/session-export", response_class=PlainTextResponse)
def api_session_export():
    """Dump everything Claude needs to analyze this session: config, current
    file states (with baseline-drift status), incident records, and the full
    in-memory event stream. Returned as a markdown blob the dashboard copies
    to the clipboard for one-shot pasting into a Claude conversation."""
    from datetime import timezone as _tz
    from io import StringIO

    out = StringIO()
    out.write("# Pipeline Guardian — Session Export\n\n")
    out.write(f"Exported: {datetime.now(_tz.utc).isoformat()}\n")
    out.write(f"Mode: {_mode().upper()}\n")
    out.write(f"Model: {llm.MODEL}\n")
    out.write(f"Run state: {RUN_STATE}\n")
    out.write(
        f"Timing: monitor={TIMING['monitor']}s, "
        f"chaos={TIMING['chaos_min']}-{TIMING['chaos_max']}s\n"
    )
    out.write(f"Events captured: {len(bus.events)}\n\n")

    # Incident summary
    summary = {"resolved": {}, "escalated": {}}
    if SUMMARY_FILE.exists():
        try:
            summary = json.loads(SUMMARY_FILE.read_text())
        except json.JSONDecodeError:
            pass
    res = sum(summary.get("resolved", {}).values())
    esc = sum(summary.get("escalated", {}).values())
    total = res + esc
    out.write("## Incident Summary\n\n")
    out.write(f"- Resolved: {res}\n- Escalated: {esc}\n- Total: {total}\n")
    if total:
        out.write(f"- Resolution rate: {100 * res // total}%\n")
    out.write(f"\nResolved by type: `{summary.get('resolved', {})}`\n")
    out.write(f"Escalated by type: `{summary.get('escalated', {})}`\n\n")

    # Current file states (with baseline drift)
    out.write("## Current File States (vs baseline)\n\n")
    for label, path, baseline_path, lang in [
        ("data/weather_source.json", DATA_FILE,
         BASELINE_DIR / "weather_source.json", "json"),
        ("pipeline.py", PIPELINE_FILE,
         BASELINE_DIR / "pipeline.py", "python"),
    ]:
        out.write(f"### `{label}`\n\n")
        if not path.exists():
            out.write("_file is missing_\n\n")
            continue
        cur = path.read_text()
        base = baseline_path.read_text() if baseline_path.exists() else ""
        drift = "DRIFTED from baseline" if cur != base else "matches baseline"
        out.write(f"Status: **{drift}** ({len(cur)} chars)\n\n")
        out.write(f"```{lang}\n{cur}\n```\n\n")

    # Recent incidents from disk (richer than summary)
    out.write("## Recent Incident Records (newest first)\n\n")
    files = sorted(
        (p for p in INCIDENTS_DIR.glob("*.json") if p.name != "summary.json"),
        reverse=True,
    )[:20]
    for p in files:
        try:
            rec = json.loads(p.read_text())
            status = "RESOLVED" if rec.get("resolved") else "ESCALATED"
            out.write(
                f"- **[{rec.get('started_at', '?')}]** {status} in "
                f"{rec.get('duration_seconds', 0)}s — "
                f"`{rec.get('failure_type', '?')}` "
                f"(conf {rec.get('diagnosis_confidence', '?')})\n"
            )
            fix = rec.get("fix_applied", "")
            if fix:
                fix_short = fix if len(fix) < 240 else fix[:237] + "..."
                out.write(f"  - fix: {fix_short}\n")
        except Exception:
            continue
    out.write("\n")

    # Full in-memory event stream (chronological)
    out.write("## Full Event Stream (chronological)\n\n```\n")
    for ev in bus.events:
        ts = ev["timestamp"][11:19]  # HH:MM:SS
        out.write(
            f"[{ts}] {ev['type']:<22} "
            f"{ev['from_agent']:>10} -> {ev['to_agent']:<10}  "
            f"{ev['message']}\n"
        )
        # include compact data dict if small (skip noisy file diffs)
        d = ev.get("data") or {}
        if d and ev["type"] != "FILE_CHANGED":
            ds = json.dumps(d)
            if len(ds) < 240:
                out.write(f"           data: {ds}\n")
    out.write("```\n")

    return out.getvalue()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    bus.connections.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        bus.connections.discard(ws)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
