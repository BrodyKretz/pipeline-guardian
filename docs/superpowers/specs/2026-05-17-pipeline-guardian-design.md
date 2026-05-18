# Pipeline Guardian — Design

**Date:** 2026-05-17
**Status:** Approved

## Summary

Two adversarial multi-agent systems plus a real-time dashboard. A **Chaos Agent**
deliberately sabotages a data pipeline. A **self-healing chain** (Monitor →
Diagnosis → Patch → Validator → Reporter) autonomously detects, classifies,
repairs, verifies, and logs the damage. A single-file web dashboard renders all
agents as nodes on a clock face with animated, source-colored message lines
streamed over a WebSocket.

Portfolio project for Brody Kretz. Hosted on GitHub, pushed actively during
development.

## Tech Stack

- Python 3.11+ (dev env is 3.12)
- Claude API (`claude-sonnet-4-6`) for agent reasoning via tool use
- FastAPI + uvicorn (dashboard + WebSocket)
- SQLite for incident logging
- APScheduler for cron-style pipeline runs and chaos triggers
- Pure single-file HTML/CSS/JS dashboard (no build step)
- python-dotenv, requests, anthropic

## Resolved Design Decisions

### 1. Baseline restore (every incident starts clean)

A `baseline/` directory holds pristine, immutable copies of `pipeline.py` and
`weather_source.json`. The **working** files are `pipeline.py` (project root) and
`data/weather_source.json` — these are what Chaos breaks and Patch fixes.

Both working files are overwritten from `baseline/` in two moments:

- On application startup.
- Immediately after the Reporter closes an incident (resolved or escalated).

Result: every incident is exactly one sabotage → one fix, deterministic and
repeatable indefinitely. No patch-soup accumulation, no non-recoverable drift.

### 2. Live code reload

The Patch Agent edits `pipeline.py` on disk while the process runs. The Monitor
and Validator therefore do **not** hold a long-lived `import pipeline`. Each run
re-loads the module from disk (`importlib.reload` / fresh exec) so patched code
takes effect within the same incident.

### 3. Concurrency / incident lock

The full healing chain runs **synchronously inside the Monitor's scheduler job**
as one straight-line call: Monitor detects failure → calls Diagnosis → Patch →
Validator → Reporter, then returns. There is no inter-agent scheduling.

- `state.incident.active: bool` plus a `threading.Lock` guard the critical section.
- The Chaos job checks `incident.active` and no-ops if an incident is in progress.
- APScheduler jobs configured with `max_instances=1` and `coalesce=True` so jobs
  never overlap or pile up.

### 4. Mock brain (API fallback)

All agent reasoning goes through one `llm.py` wrapper exposing a single
`call_with_tools(...)` interface. If `ANTHROPIC_API_KEY` is unset, or the
Anthropic API errors, the wrapper transparently routes to a **deterministic
rule-based responder** that returns the exact tool-call shape Claude would.

- Real-API path and mock path are identical agent code; only the responder swaps.
- Mock-diagnosis classifies from **real signals only** (missing file, `[]`,
  string-typed temps, null temps, renamed keys, non-ISO dates, 10× row count).
  It never reads the stored sabotage type, so the agent choreography is genuinely
  exercised without paid reasoning.
- Per spec note 5: any Claude failure logs the error and escalates the incident
  rather than crashing.

### 5. WebSocket bridge (thread → async)

Agents run in APScheduler worker threads; FastAPI is async. `state.emit()`:

1. Appends the event to the append-only event list (and the active incident's
   event chain).
2. Hands the event to the event loop via `loop.call_soon_threadsafe` onto an
   `asyncio.Queue`.
3. A background task drains the queue and broadcasts to all live WS clients;
   sockets that fail on send are pruned.

### 6. GitHub

- New repo created via `gh` (account: BrodyKretz), pushed actively as work lands.
- `.gitignore` excludes `.env`, `output/*`, `incidents/*` (keep `.gitkeep`),
  `__pycache__`, `*.db`, the working mutable files' generated artifacts.
- `.env` is **never** committed. `.env.example` with `ANTHROPIC_API_KEY=` is
  committed instead.
- Strong `README.md`: what it is, the adversarial concept, architecture diagram
  (agents + flow), quickstart, mock-mode note, screenshots placeholder, tech
  stack, project layout.

## Project Structure

```
pipeline-guardian/
├── main.py                  # FastAPI app + APScheduler startup
├── config.py                # All constants: MODEL, intervals, DEMO_FAST, paths
├── llm.py                   # Claude tool-use wrapper + deterministic mock brain
├── pipeline.py              # WORKING ETL pipeline (mutated by chaos/patch)
├── state.py                 # Event bus, incident state, WS registry, lock
├── baseline/
│   ├── pipeline.py          # Pristine pipeline source
│   └── weather_source.json  # Pristine 20-record dataset
├── agents/
│   ├── chaos_agent.py
│   ├── monitor_agent.py
│   ├── diagnosis_agent.py
│   ├── patch_agent.py
│   ├── validator_agent.py
│   └── reporter_agent.py
├── tools/
│   ├── file_tools.py        # read_file, write_file, list_files
│   ├── pipeline_tools.py    # run_pipeline, get_last_output
│   └── log_tools.py         # write_incident_log, read_incident_log
├── dashboard/
│   └── index.html           # Full single-file visual dashboard
├── data/
│   └── weather_source.json  # WORKING data (restored from baseline)
├── output/.gitkeep
├── incidents/.gitkeep
├── tests/                   # pytest suite
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## The Pipeline

Reads `data/weather_source.json`; expects schema
`{ "temp": float, "city": str, "humidity": int, "timestamp": str (ISO) }`.
Transforms: F→C temp conversion, strip whitespace from `city`, validate
`humidity` in 0–100. Loads a clean summary to `output/daily_summary.json`.
Catches **all** exceptions and returns
`{ "success": bool, "rows_processed": int, "error": str|None, "error_type": str|None }`
— never raises to the caller.

## Sabotage Types (Chaos Agent)

`SCHEMA_RENAME`, `TYPE_CORRUPTION`, `NULL_INJECTION`, `EMPTY_DATA`,
`MISSING_FILE`, `DATE_FORMAT`, `DUPLICATE_ROWS`. Chaos uses Claude (or mock) to
pick a sabotage weighted away from recent history. Emits `SABOTAGE_PLANNED`
(→pipeline) then `SABOTAGE_APPLIED` (→monitor); stores the true type in state for
the Reporter's record (not exposed to Diagnosis). Runs on a random 180–360s
interval, only when no incident is active.

## Agent Chain

| Agent | Trigger | Emits |
|---|---|---|
| Monitor | every 60s | `PIPELINE_TRIGGERED`, then `PIPELINE_HEALTHY` or `FAILURE_DETECTED` |
| Diagnosis | by Monitor on failure | `DIAGNOSIS_STARTED`, `DIAGNOSIS_COMPLETE`; `ESCALATE` if conf<0.6 or UNKNOWN |
| Patch | by Diagnosis | `PATCH_STARTED`, `PATCH_APPLIED` |
| Validator | after Patch | `VALIDATION_STARTED`, then `VALIDATION_PASSED` or `VALIDATION_FAILED`+`ESCALATE` |
| Reporter | end of every incident | `INCIDENT_CLOSED`; writes incident JSON + updates summary; sets `incident.active=False`; triggers baseline restore |

**Diagnosis** classifies into one of the 7 types or `UNKNOWN` with
`{ failure_type, confidence, reasoning, suggested_fix }`. Tools: read pipeline
error, read/inspect data file, read `pipeline.py`.

**Patch** confidence gating: `≥0.85` apply directly; `0.60–0.84` apply but log
"unverified"; `<0.60` no code change, escalate. Tools: `read_file`,
`write_file`, `restore_data_file`, `rewrite_pipeline_section`. Per-type fixes:
SCHEMA_RENAME → adjust field access; TYPE_CORRUPTION → coerce/clean; NULL_INJECTION
→ filter nulls; EMPTY_DATA/MISSING_FILE → `restore_data_file`; DATE_FORMAT →
flexible parsing; DUPLICATE_ROWS → dedupe step. Patch may only touch `pipeline.py`
and data files — never agent code.

**Reporter** writes `incidents/YYYY-MM-DD_HH-MM-SS.json` (incident_id, timestamps,
failure_type, chaos_sabotage, diagnosis_confidence, fix_applied, resolved,
duration_seconds, event_chain) and maintains `incidents/summary.json` running
totals by type. Incidents also logged to SQLite.

## Dashboard

Single `dashboard/index.html`, dark `#0a0a0f`. Agents on a clock-face ring:
CHAOS (red, larger, ⚡), MONITOR (yellow, 👁), DIAGNOSIS (orange, 🔍), PATCH
(blue, 🔧), VALIDATOR (green, ✓), REPORTER (purple, 📋); PIPELINE (grey, ⚙) in
center off-ring. WS at `ws://localhost:8000/ws`. On each event: append to live
log, draw a source-colored line from→to with a CSS-animated traveling dot and
event-type label, fade after 2s, update node status glow (idle/active/error) and
last-action text. SABOTAGE events trigger aggressive red CHAOS pulse + big
center sabotage-type flash + thick red CHAOS→PIPELINE line. Panels: bottom-left
scrolling color-coded log; bottom-right current incident + last 5 summaries from
`/api/incidents`; top bar health/uptime/total incidents/resolution rate.

## FastAPI Endpoints

- `GET /` → dashboard
- `GET /api/incidents` → `summary.json` + last 10 incident files
- `GET /api/state` → active incident + recent events
- `WebSocket /ws` → live event stream

Startup: init state → restore working files from baseline → start APScheduler
(monitor 60s; chaos random 180–360s, incident-gated) → emit `SYSTEM_STARTED`.

## Testing (pytest)

- Pipeline: healthy run succeeds; each of the 7 sabotages → correct structured
  error (no raise).
- Event bus: `emit` appends + queues; incident event-chain accumulation.
- Baseline restore: working files byte-equal baseline after restore.
- Mock brain: classifier maps each real signal to the correct failure type.
- End-to-end agent loop verifiable in mock mode with no API key.

## Out of Scope (YAGNI)

No auth, no multi-pipeline support, no configurable parameters beyond `config.py`
constants, no DB migrations framework, no deployment infra. `DEMO_FAST` toggle in
`config.py` shrinks intervals for live demos — the only concession to operability.
