# 🛡️ Pipeline Guardian

**Two AI agent systems at war over a data pipeline — and a live dashboard to watch it happen.**

A **Chaos Agent** continuously sabotages an ETL pipeline. A **self-healing
agent chain** — Monitor → Diagnosis → Patch → Validator → Reporter — detects,
diagnoses, repairs, and verifies every break autonomously. A real-time
dashboard renders all agents as nodes on a clock face with animated messages
flowing between them as they fight.

Every agent reasons through the Claude API via tool use. With no API key it
falls back to a deterministic rule-based "mock brain" so the entire system
runs, animates, and self-heals end-to-end **for free**.

---

## How it works

```
          ┌─────────────────────────────────────────────┐
          │                  CHAOS ⚡                     │
          │   picks & applies 1 of 7 sabotages to the     │
          │   data source every 3–6 min (if no incident)  │
          └───────────────────────┬─────────────────────┘
                                   │ corrupts
                                   ▼
                          data/weather_source.json
                                   │
   MONITOR 👁  every 60s ──────────┘ runs pipeline.py
        │ failure / row-count anomaly
        ▼
   DIAGNOSIS 🔍 ── classifies root cause from observable signals only
        │ (confidence-scored; <0.6 or UNKNOWN ⇒ escalate)
        ▼
   PATCH 🔧 ── applies the targeted fix
        │ ≥0.85 direct · 0.60–0.84 unverified · <0.60 escalate
        ▼
   VALIDATOR ✓ ── re-runs pipeline, checks rows + schema
        │ pass / fail
        ▼
   REPORTER 📋 ── writes incident JSON + summary + SQLite,
                  then restores pipeline.py & data to a clean baseline
```

Every incident starts from a pristine baseline, so each round is one
sabotage → one fix: deterministic, repeatable, and never degrades.

### The 7 sabotages

| Sabotage | What it does | The fix |
|---|---|---|
| `SCHEMA_RENAME` | `temp`→`temperature`, `city`→`location` | rewrite field access with fallback |
| `TYPE_CORRUPTION` | temps become `"72.4F"` strings | numeric coercion before transform |
| `NULL_INJECTION` | `temp: null` on ~30% of rows | filter null-temp rows |
| `EMPTY_DATA` | file becomes `[]` | restore data from baseline |
| `MISSING_FILE` | data file deleted | restore data from baseline |
| `DATE_FORMAT` | ISO → `MM/DD/YYYY HH:MM` | flexible timestamp parsing |
| `DUPLICATE_ROWS` | every row ×10 | deduplication step |

---

## Quickstart

```bash
git clone https://github.com/BrodyKretz/pipeline-guardian.git
cd pipeline-guardian
pip install -r requirements.txt

cp .env.example .env          # optional: add ANTHROPIC_API_KEY for real reasoning

python main.py                # open http://localhost:8000
```

Within a few minutes the Chaos Agent breaks the pipeline and you watch the
healing chain fix it live.

**Fast demo:** `DEMO_FAST=1 python main.py` shrinks the intervals
(monitor 15s, chaos 30–60s) so a full incident plays out in under a minute.

### Mock mode vs. real Claude

- **No `ANTHROPIC_API_KEY`** → deterministic mock brain. Full system runs and
  self-heals; diagnosis classifies from real observed signals (it never peeks
  at which sabotage was applied), so the agent choreography is genuine.
- **Valid `ANTHROPIC_API_KEY`** → agents reason through Claude
  (`claude-sonnet-4-6`) via tool use. Any API error degrades gracefully back
  to the mock path and the incident escalates rather than crashing.

---

## Project layout

```
main.py            FastAPI app + APScheduler + WebSocket
config.py          all constants (model, intervals, thresholds, paths)
llm.py             Claude tool-use wrapper + deterministic mock brain
pipeline.py        the ETL pipeline (mutated by chaos/patch at runtime)
state.py           event bus, incident state, thread→async WS bridge
restore.py         baseline restore (clean slate per incident)
baseline/          pristine pipeline.py + 20-record dataset
agents/            chaos, monitor, diagnosis, patch, validator, reporter
tools/             file / pipeline / log tools + Claude tool schemas
dashboard/         single-file animated dashboard (no build step)
incidents/         per-incident JSON + summary.json + SQLite log
tests/             pytest suite (45 tests)
```

## Testing

```bash
pytest -q     # 45 tests: pipeline, event bus, restore, mock brain,
              # tools, chaos, and full healing-chain e2e for all 7 sabotages
```

The end-to-end chain is fully verifiable in mock mode with no API key.

## Tech stack

Python 3.11+ · Claude API (tool use) · FastAPI · uvicorn · APScheduler ·
SQLite · WebSockets · vanilla HTML/CSS/JS · pytest

---

*Built as a portfolio project exploring autonomous multi-agent systems,
adversarial self-healing, and real-time agent observability.*
