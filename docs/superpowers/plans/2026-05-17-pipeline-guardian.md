# Pipeline Guardian Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An adversarial multi-agent system where a Chaos Agent sabotages an ETL pipeline and a self-healing agent chain autonomously repairs it, with a real-time WebSocket dashboard.

**Architecture:** Synchronous healing chain inside the monitor's scheduler job; thread→async WebSocket bridge; deterministic mock-brain fallback when no API key; baseline restore after every incident for deterministic repeatable rounds.

**Tech Stack:** Python 3.12, anthropic, FastAPI, uvicorn, APScheduler, SQLite, python-dotenv, pytest.

---

## File Responsibilities

- `config.py` — constants: MODEL, paths, intervals, DEMO_FAST, confidence thresholds, healthy dataset spec.
- `state.py` — `EventBus` (events, WS registry, asyncio queue bridge, incident state, threading.Lock).
- `baseline/pipeline.py` + `baseline/weather_source.json` — pristine sources.
- `pipeline.py` — working ETL (copy of baseline); mutated by chaos/patch.
- `restore.py` — baseline restore helper (working files ← baseline).
- `llm.py` — `call_with_tools()`: real Anthropic tool-use OR deterministic mock brain.
- `tools/*.py` — file/pipeline/log tool implementations + JSON tool schemas.
- `agents/*.py` — six agents, each `run(state, ...)` driving `llm.call_with_tools`.
- `db.py` — SQLite incident logging.
- `main.py` — FastAPI app, endpoints, WS, APScheduler wiring, startup.
- `dashboard/index.html` — single-file dashboard.
- `tests/` — pytest suite.

---

## Task 1: Project scaffold & config

**Files:**
- Create: `requirements.txt`, `.env.example`, `config.py`, `output/.gitkeep`, `incidents/.gitkeep`, `data/.gitkeep`

- [ ] **Step 1:** Write `requirements.txt`:
```
anthropic
fastapi
uvicorn
apscheduler
python-dotenv
requests
pytest
```

- [ ] **Step 2:** Write `.env.example`: `ANTHROPIC_API_KEY=`

- [ ] **Step 3:** Write `config.py`:
```python
import os
from pathlib import Path

ROOT = Path(__file__).parent
MODEL = "claude-sonnet-4-6"
DEMO_FAST = os.getenv("DEMO_FAST", "0") == "1"

MONITOR_INTERVAL_SEC = 15 if DEMO_FAST else 60
CHAOS_MIN_SEC = 30 if DEMO_FAST else 180
CHAOS_MAX_SEC = 60 if DEMO_FAST else 360

DATA_FILE = ROOT / "data" / "weather_source.json"
OUTPUT_FILE = ROOT / "output" / "daily_summary.json"
PIPELINE_FILE = ROOT / "pipeline.py"
BASELINE_DIR = ROOT / "baseline"
INCIDENTS_DIR = ROOT / "incidents"
DB_FILE = ROOT / "incidents" / "incidents.db"

CONF_DIRECT = 0.85
CONF_UNVERIFIED = 0.60
SABOTAGE_TYPES = ["SCHEMA_RENAME", "TYPE_CORRUPTION", "NULL_INJECTION",
                  "EMPTY_DATA", "MISSING_FILE", "DATE_FORMAT", "DUPLICATE_ROWS"]
AGENTS = ["chaos", "monitor", "diagnosis", "patch", "validator",
          "reporter", "pipeline", "system"]
HEALTHY_ROW_COUNT = 20
```

- [ ] **Step 4:** `pip install -r requirements.txt` in py312. Expected: all install OK.

- [ ] **Step 5:** Commit & push: `git add -A && git commit -m "feat: scaffold + config" && git push`

---

## Task 2: Baseline dataset & pipeline (TDD)

**Files:**
- Create: `baseline/weather_source.json`, `baseline/pipeline.py`, `pipeline.py`, `tests/test_pipeline.py`

- [ ] **Step 1:** Generate `baseline/weather_source.json` — exactly 20 records:
```python
# scripts: produce 20 dicts {"temp": float, "city": str, "humidity": int 0-100, "timestamp": ISO}
```
Write a small generator producing valid varied data; save to `baseline/weather_source.json`. Copy to `data/weather_source.json`.

- [ ] **Step 2:** Write `tests/test_pipeline.py` failing test:
```python
import json, importlib, shutil
from config import BASELINE_DIR, DATA_FILE, OUTPUT_FILE

def reset():
    shutil.copy(BASELINE_DIR/"weather_source.json", DATA_FILE)

def test_healthy_run_succeeds():
    reset()
    import pipeline; importlib.reload(pipeline)
    r = pipeline.run()
    assert r["success"] is True
    assert r["rows_processed"] == 20
    assert r["error"] is None
    out = json.loads(OUTPUT_FILE.read_text())
    assert len(out) == 20
    assert isinstance(out[0]["temp"], float)  # Celsius
```

- [ ] **Step 3:** Run `pytest tests/test_pipeline.py -v` → FAIL (no `pipeline.run`).

- [ ] **Step 4:** Write `baseline/pipeline.py` (then copy to `pipeline.py`):
```python
import json
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "weather_source.json"
OUTPUT_FILE = Path(__file__).parent / "output" / "daily_summary.json"

def run():
    rows_processed = 0
    try:
        if not DATA_FILE.exists():
            return {"success": False, "rows_processed": 0,
                    "error": f"data file not found: {DATA_FILE}",
                    "error_type": "FileNotFoundError"}
        raw = json.loads(DATA_FILE.read_text())
        if not isinstance(raw, list) or len(raw) == 0:
            return {"success": False, "rows_processed": 0,
                    "error": "empty or non-list dataset", "error_type": "EmptyData"}
        out = []
        for rec in raw:
            temp_f = rec["temp"]
            temp_c = round((float(temp_f) - 32) * 5.0 / 9.0, 2)
            city = rec["city"].strip()
            humidity = int(rec["humidity"])
            if not 0 <= humidity <= 100:
                raise ValueError(f"humidity out of range: {humidity}")
            ts = rec["timestamp"]
            out.append({"city": city, "temp": temp_c,
                        "humidity": humidity, "timestamp": ts})
            rows_processed += 1
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(out, indent=2))
        return {"success": True, "rows_processed": rows_processed,
                "error": None, "error_type": None}
    except Exception as e:
        return {"success": False, "rows_processed": rows_processed,
                "error": str(e), "error_type": type(e).__name__}
```

- [ ] **Step 5:** Run `pytest tests/test_pipeline.py -v` → PASS.

- [ ] **Step 6:** Add parametrized sabotage tests (each sabotage applied to data → `run()` returns `success=False` and does not raise). Verify all 7 fail cleanly.

- [ ] **Step 7:** Commit & push.

---

## Task 3: State / event bus (TDD)

**Files:** Create `state.py`, `tests/test_state.py`

- [ ] **Step 1:** Failing test:
```python
from state import EventBus
def test_emit_appends_and_tracks_incident():
    bus = EventBus()
    bus.start_incident()
    bus.emit("monitor", "diagnosis", "FAILURE_DETECTED", "boom", {"x": 1})
    assert len(bus.events) == 1
    e = bus.events[0]
    assert e["from_agent"] == "monitor" and e["to_agent"] == "diagnosis"
    assert e["type"] == "FAILURE_DETECTED" and e["data"] == {"x": 1}
    assert bus.incident["active"] is True
    assert len(bus.incident["events"]) == 1
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Implement `EventBus`: `events` list; `emit()` builds `{id, timestamp, from_agent, to_agent, type, message, data}`, appends, appends to active incident, and if an asyncio loop+queue are registered, `loop.call_soon_threadsafe(queue.put_nowait, event)`; `connections` set; `register_loop(loop, queue)`; `start_incident()/close_incident()`; `incident` dict `{active, failure_type, sabotage_type, start_time, events}`; `threading.Lock` as `bus.lock`.

- [ ] **Step 4:** Run → PASS. Add test that emit without a loop registered does not raise.

- [ ] **Step 5:** Commit & push.

---

## Task 4: Restore helper (TDD)

**Files:** Create `restore.py`, `tests/test_restore.py`

- [ ] **Step 1:** Failing test: corrupt `data/weather_source.json` and `pipeline.py`, call `restore_all()`, assert both byte-equal their `baseline/` counterparts.

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Implement `restore_all()` (copy `baseline/pipeline.py`→`pipeline.py`, `baseline/weather_source.json`→`data/weather_source.json`) and `restore_data_only()`.

- [ ] **Step 4:** Run → PASS. Commit & push.

---

## Task 5: LLM wrapper + mock brain (TDD)

**Files:** Create `llm.py`, `tests/test_llm_mock.py`

- [ ] **Step 1:** Failing tests for the mock classifier — given a synthetic pipeline error + data-file state, `mock_diagnose()` returns correct `failure_type` for each of the 7 signals (missing file, `[]`, string temps, null temps, renamed keys `temperature`/`location`, non-ISO date, 10×20=200 rows).

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Implement `llm.py`:
  - `USE_REAL = bool(os.getenv("ANTHROPIC_API_KEY"))`.
  - `call_with_tools(system, messages, tools, tool_executor)` — if real key: loop Anthropic `messages.create` with `tools`, dispatch `tool_use` blocks through `tool_executor`, feed `tool_result`s back until `end_turn`; on any exception return `{"escalate": True, "error": str(e)}`.
  - Mock path: pure functions `mock_pick_sabotage(recent)`, `mock_diagnose(error, data_state)`, `mock_patch_plan(failure_type)` returning the same dict shapes the agents expect. `mock_diagnose` inspects real signals only.

- [ ] **Step 4:** Run → PASS (mock classifier correct for all 7). Commit & push.

---

## Task 6: Tools layer

**Files:** Create `tools/file_tools.py`, `tools/pipeline_tools.py`, `tools/log_tools.py`, `tools/schemas.py`, `db.py`, `tests/test_tools.py`

- [ ] **Step 1:** Failing test: `run_pipeline()` reloads and runs pipeline returning the result dict; `read_file`/`write_file`/`list_files` round-trip; `write_incident_log` inserts a row readable by `read_incident_log`.

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Implement:
  - `file_tools`: `read_file(path)`, `write_file(path, content)`, `list_files(dir)` — restricted to project root.
  - `pipeline_tools`: `run_pipeline()` (`importlib.reload`), `get_last_output()`, `restore_data_file()`, `rewrite_pipeline_section(old, new)` (read pipeline.py, str-replace, write; error if `old` absent).
  - `db.py`: SQLite `incidents` table; `init_db()`, `insert_incident(record)`, `recent_incidents(n)`.
  - `log_tools`: `write_incident_log`/`read_incident_log` over `db.py`.
  - `schemas.py`: Anthropic tool JSON schemas for each tool, grouped per agent.

- [ ] **Step 4:** Run → PASS. Commit & push.

---

## Task 7: Chaos agent

**Files:** Create `agents/chaos_agent.py`, `tests/test_chaos.py`

- [ ] **Step 1:** Failing test: each sabotage function transforms baseline data into the expected broken state (assert structurally); `run_chaos(bus)` emits `SABOTAGE_PLANNED` then `SABOTAGE_APPLIED` and sets `bus.incident["sabotage_type"]`.

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Implement 7 sabotage functions operating on `DATA_FILE`/`PIPELINE_FILE`; `run_chaos(bus)`: pick via `llm` (real tool-use to choose, else `mock_pick_sabotage`) weighted off recent history, emit planned, apply, emit applied, store true type in incident state (not surfaced to diagnosis).

- [ ] **Step 4:** Run → PASS. Commit & push.

---

## Task 8: Healing chain agents

**Files:** Create `agents/monitor_agent.py`, `diagnosis_agent.py`, `patch_agent.py`, `validator_agent.py`, `reporter_agent.py`, `tests/test_healing_chain.py`

- [ ] **Step 1:** Failing end-to-end test (mock mode, no API key): for each sabotage — reset baseline, apply sabotage, run `monitor.tick(bus)`; assert incident opens, diagnosis classifies correctly, patch applies, validator passes, reporter writes incident JSON + updates `summary.json`, `incident.active` ends False, and baseline is restored (working files == baseline).

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Implement:
  - `monitor.tick(bus)`: emit `PIPELINE_TRIGGERED`, run pipeline; success → `PIPELINE_HEALTHY`; failure → `start_incident`, emit `FAILURE_DETECTED`, call diagnosis (synchronous chain under `bus.lock`).
  - `diagnosis.run(bus, error)`: emit `DIAGNOSIS_STARTED`; `llm.call_with_tools` with read-file/read-pipeline/inspect-data tools → `{failure_type, confidence, reasoning, suggested_fix}`; if conf<0.6 or UNKNOWN emit `ESCALATE`→reporter and stop; else emit `DIAGNOSIS_COMPLETE`→patch and continue.
  - `patch.run(bus, diagnosis)`: emit `PATCH_STARTED`; gating (≥0.85 apply / 0.60–0.84 apply+unverified / <0.60 escalate); per-type fix via tools (`restore_data_file`, `rewrite_pipeline_section`, `write_file`); emit `PATCH_APPLIED`→validator.
  - `validator.run(bus)`: emit `VALIDATION_STARTED`; rerun pipeline; check output exists + row count + schema; emit `VALIDATION_PASSED` or `VALIDATION_FAILED`+`ESCALATE`.
  - `reporter.run(bus, resolved)`: write `incidents/<ts>.json` (full schema), update `summary.json`, insert SQLite row, emit `INCIDENT_CLOSED`, `close_incident()`, then `restore.restore_all()`.

- [ ] **Step 4:** Run → PASS for all 7 sabotages. Commit & push.

---

## Task 9: FastAPI app + scheduler

**Files:** Create `main.py`, `tests/test_api.py`

- [ ] **Step 1:** Failing test (TestClient): `GET /` returns HTML; `GET /api/state` returns JSON with `incident`/`events`; `GET /api/incidents` returns `{summary, recent}`.

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3:** Implement `main.py`: FastAPI app; on startup `restore_all()`, `init_db()`, register asyncio loop+queue on bus, start drain→broadcast task, start APScheduler (monitor every `MONITOR_INTERVAL_SEC`, chaos at random `CHAOS_MIN..MAX` re-scheduling itself and skipping if `incident.active`), emit `SYSTEM_STARTED`. Endpoints `/`, `/api/incidents`, `/api/state`, `WebSocket /ws` (add/remove from `bus.connections`). APScheduler jobs `max_instances=1, coalesce=True`. `if __name__=="__main__": uvicorn.run(...)` port 8000.

- [ ] **Step 4:** Run → PASS. Manually `python main.py` with `DEMO_FAST=1`, confirm `SYSTEM_STARTED` log and `/` loads. Commit & push.

---

## Task 10: Dashboard

**Files:** Create `dashboard/index.html`

- [ ] **Step 1:** Build single-file dashboard per spec: dark `#0a0a0f`; SVG/absolute clock-face ring of 6 agent nodes + central PIPELINE; WS to `ws://localhost:8000/ws`; on event → append color-coded log line, draw source-colored line from→to with CSS-animated traveling dot + type label fading after 2s, update node glow (idle/active/error) + last-action text; SABOTAGE → red CHAOS pulse + big center flash + thick red CHAOS→PIPELINE line; bottom-left scrolling log; bottom-right current incident + last 5 from `/api/incidents`; top bar health/uptime/total/resolution-rate.

- [ ] **Step 2:** Run `DEMO_FAST=1 python main.py`, open browser, verify with Playwright screenshot: nodes render, a forced chaos cycle animates lines, log populates. Iterate to fix visual issues.

- [ ] **Step 3:** Commit & push.

---

## Task 11: README & polish

**Files:** Create `README.md`

- [ ] **Step 1:** Write strong README: concept (adversarial agents), architecture diagram (ASCII), feature list, quickstart (`pip install`, `.env`, `python main.py`), mock-mode explanation (runs with no API key), `DEMO_FAST`, project layout, tech stack, screenshot placeholder, testing (`pytest`).

- [ ] **Step 2:** Run full `pytest` → all green. Capture a dashboard screenshot into `docs/`.

- [ ] **Step 3:** Final commit & push. Verify GitHub repo reflects all work and `.env` is absent.

---

## Self-Review

- **Spec coverage:** pipeline (T2), 7 sabotages (T7), event bus (T3), baseline restore (T4), mock brain (T5), tools (T6), 6 agents + confidence gating + escalation (T7–T8), reporter JSON/summary/SQLite (T8), FastAPI + WS + scheduler + startup (T9), dashboard visuals (T10), README/GitHub (T1,T11). All spec sections mapped.
- **Placeholders:** none — code shown for core; agent/dashboard tasks specify exact behaviors, interfaces, emitted event names from the spec.
- **Type consistency:** `bus.emit(from,to,type,message,data)`, `incident` keys, `call_with_tools` signature, agent `run(bus, ...)` shapes, diagnosis dict `{failure_type,confidence,reasoning,suggested_fix}` consistent across T3–T9.
