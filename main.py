import asyncio
import json
import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import llm
from agents import monitor_agent
from agents.chaos_agent import run_chaos
from config import (
    CHAOS_MAX_SEC,
    CHAOS_MIN_SEC,
    INCIDENTS_DIR,
    MONITOR_INTERVAL_SEC,
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


def _status():
    return {"run_state": RUN_STATE, "mode": _mode(), "has_key": _has_key()}


def _monitor_job():
    if RUN_STATE != "running":
        return
    try:
        monitor_agent.tick(bus)
    except Exception as e:  # never let a job crash the scheduler
        bus.emit("monitor", "system", "ERROR", f"monitor job failed: {e}")


def _chaos_job():
    try:
        if RUN_STATE == "running":
            run_chaos(bus)
    except Exception as e:
        bus.emit("chaos", "system", "ERROR", f"chaos job failed: {e}")
    finally:
        delay = random.randint(CHAOS_MIN_SEC, CHAOS_MAX_SEC)
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
    bus.emit("system", "system", "SYSTEM_STARTED", "Pipeline Guardian online")
    if not os.getenv("PG_DISABLE_SCHEDULER"):
        scheduler.add_job(
            _monitor_job,
            "interval",
            seconds=MONITOR_INTERVAL_SEC,
            id="monitor",
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            _chaos_job,
            "date",
            run_date=datetime.now()
            + timedelta(seconds=random.randint(CHAOS_MIN_SEC, CHAOS_MAX_SEC)),
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
        RUN_STATE = "paused"
        bus.emit("system", "system", "AUTOMATION_PAUSED", "Automation paused")
    elif action == "stop":
        with bus.lock:
            RUN_STATE = "stopped"
            if bus.incident["active"]:
                bus.close_incident()
                restore_all()
        bus.emit(
            "system",
            "system",
            "AUTOMATION_STOPPED",
            "Automation stopped; active incident cleared, baseline restored",
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
