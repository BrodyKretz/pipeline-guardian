# Pipeline Guard

**A multi-agent self-healing data pipeline. Chaos breaks it. Five other agents detect, diagnose, repair, validate, and log every break — live, on a dashboard you can watch.**

When you flip the dashboard to **AI mode**, every agent reasons through Claude via tool use. Chaos invents realistic upstream-feed failures by reading your actual data and pipeline source. Diagnosis classifies them in free text. Patch writes durable, defensive fixes that *accumulate* — the pipeline genuinely hardens over time. Validator judges output structure. None of them ever see the baseline (it's not an answer key) or the colored damage/heal overlays (those are for you).

In **mock mode** the same architecture runs on a deterministic 7-enum path. No API key needed. Each round resolves in milliseconds.

---

## Drop in any dataset

The pipeline is dataset-agnostic. Hit the "choose file…" button in the *Agent Timing* panel and upload any `.json`, `.jsonl`, or `.csv` — songs, transactions, sensor readings, anything. The system:

1. Parses it (handles JSON arrays, envelope dicts like `{data: [...]}`, JSONL lines, CSV with numeric coercion).
2. **Derives a compliance profile** at ingest: per-field type, nullability, observed min/max, string enums (when small enough).
3. Saves the records + profile to disk; subsequent pipeline runs validate against that profile.
4. **Surfaces the profile to every AI agent** in its system prompt — chaos drifts from it, patch heals toward it, validator enforces it. The profile is AI-visible (unlike the baseline).

The default 20-record weather dataset is what ships with the repo; uploading replaces it. Click STOP or restart to reseed the weather baseline.

---

## What you see

```
              ┌───────────────────────────────┐
              │           CHAOS ⚡             │
              │  Invents one realistic upstream│
              │  failure (schema/type/format/  │
              │  encoding/value/volume drift)  │
              │  and mutates the data feed.    │
              └───────────────┬───────────────┘
                              │ damages
                              ▼
                  data/weather_source.json
                              │
   MONITOR   every 15–60s ──┘ runs pipeline.py in a subprocess
        │ failure / row-count anomaly
        ▼
   DIAGNOSIS  reads both files; submits free-form root cause + confidence
        │ <0.60 → escalate
        ▼
   PATCH  reads files (NOT baseline); writes a defensive fix to pipeline.py
        │      or cleans/clamps existing data. Never invents records.
        │      Can dry_run + retry once with validator feedback.
        ▼
   VALIDATOR ✓ re-runs the pipeline; judges output structural integrity
        │ pass / fail
        ▼
   REPORTER  logs the incident (no baseline restore — heals persist)
```

**Heals accumulate.** When patch widens `pipeline.py` to handle `temperature` *or* `temp`, that widening stays. The next chaos round meets a more robust pipeline. Over a long demo you watch the system genuinely learn.

---

## Quickstart

```bash
git clone https://github.com/BrodyKretz/pipeline-guardian.git
cd pipeline-guardian
pip install -r requirements.txt

cp .env.example .env          # optional: ANTHROPIC_API_KEY for AI mode

python main.py                # open http://localhost:8000
```

For fast demos: `DEMO_FAST=1 python main.py` (15s monitor, 30–60s chaos).

The system boots in **MOCK** by design — a saved API key never silently turns on paid calls. Flip to **AI** in the dashboard top bar (paste your key inline if needed).

---

## The dashboard

A single-file vanilla-JS dashboard at `dashboard/index.html`. Two views toggled in the top bar:

**GRAPH view** — agents arranged in a graph at top-left. Each agent lights up when it emits an event; wires animate between sender and receiver. Side panels:
- *Agent Timing* — change monitor + chaos intervals + model assignments live
- *Watched Files* — compact diff view of the working files
- *Live Event Stream* — every event the bus has seen
- *Incident Status* — current incident + history with resolution rate

**FILES view** — `data/weather_source.json` and `pipeline.py` shown side-by-side, with **per-agent colored diffs**. Damage flashes red, heals flash in the patching agent's color, restores go neutral. Unhealed damage persists visibly. A small *Pipeline State* panel on the left shows the current incident state in one glance.

**Top-bar controls** include:
- ▶ Start / ⏸ Pause / ⏹ Stop (Stop is the explicit full reset)
- ⚡ CHAOS button + category dropdown (fire chaos on demand, optionally biased to schema/type/format/encoding/value/volume/unit/structural drift)
- MOCK / AI mode toggle
- GRAPH / FILES view toggle
-  export button — copies a markdown session dump (events, files, incidents, current state) to your clipboard for pasting into a Claude conversation
- Live counters: uptime, incidents, resolution rate, tokens (in/out) + cost estimate

---

## What the AI is blind to

Two pieces of harness ground-truth the agents never receive. This is the spine of the design:

1. **The baseline.** `baseline/weather_source.json` and `baseline/pipeline.py` exist only to seed the system on startup and to provide a manual STOP-button reset. No agent reads them during reasoning. Patch must reconstruct correctness from the *current* files alone.
2. **Color / damage-vs-heal tags.** The dashboard's per-agent coloring is computed from `FILE_CHANGED` events. Those events are never returned to any AI tool — agents only read raw file text. The diff overlay exists for you, not the model.

The principle: the model has to *find* the problem like a real on-call engineer who wasn't told what changed.

---

## Safety

AI mode runs untrusted generated code. Three guardrails:

- **File whitelist.** Chaos and patch may only write `data/weather_source.json` and `pipeline.py`. Baseline, agent code, `llm.py`, `main.py` — all unreachable.
- **Subprocess pipeline execution.** Every pipeline run is a fresh `python -c` subprocess with a 10-second timeout. Generated infinite loops or syntax errors surface as ordinary failure results; they cannot wedge the server.
- **Hard write-guards.** Chaos can't empty the file or grow the record count (no resurrecting dropped stations). Patch can't fabricate records or rewrite over unparseable data — must edit `pipeline.py` or escalate.

---

## Mock mode vs AI mode

|                          | MOCK (default)                                  | AI (opt-in via dashboard)                      |
| ------------------------ | ----------------------------------------------- | ---------------------------------------------- |
| API calls                | Zero                                            | Per agent, per incident                        |
| Chaos                    | Picks one of 7 canned sabotages                 | Invents one creative realistic mutation        |
| Diagnosis                | Rule-based classifier from observable signals   | Free-form, multi-turn tool loop                |
| Patch                    | Hardcoded fix per failure type                  | Generative; writes defensive code/data edits   |
| Validator                | Schema + row-count check                        | AI judges structural integrity                 |
| Cost                     | $0                                              | ~$0.01–0.05 per incident on Sonnet             |
| Repeatable               | Yes — every round resolves identically          | No — chaos diversifies, pipeline hardens       |

---

## Project layout

```
main.py            FastAPI app + APScheduler + WebSocket + session-export endpoint
config.py          paths, thresholds, writable-file whitelist, timing defaults
llm.py             Claude tool-use loop, per-agent generators, token tracking
pipeline.py        the ETL pipeline (mutated by chaos / patched by patch at runtime)
state.py           event bus, incident state, thread→async websocket bridge
restore.py         baseline reset (startup + STOP button only)
baseline/          pristine pipeline.py + 20-record 10-field weather dataset
agents/            chaos, monitor, diagnosis, patch, validator, reporter
tools/             file events, pipeline subprocess runner, Anthropic tool schemas
dashboard/         single-file vanilla-JS dashboard (no build step)
incidents/         per-incident JSON + summary.json + SQLite log
tests/             pytest suite (79 tests; AI agents tested with a stubbed client)
docs/superpowers/  design specs and implementation plans for each major phase
```

---

## Testing

```bash
pytest -q     # 79 tests: pipeline, event bus, file-change emitter,
              # subprocess pipeline, mock + AI agents, full healing chain,
              # AI-blindness assertion, write-guards, retry-once
```

AI-agent tests use a scripted `FakeClient` — full coverage with zero live API calls.

---

## Tech stack

Python 3.12 · Claude API (tool use) · FastAPI · uvicorn · APScheduler · SQLite · WebSockets · vanilla HTML/CSS/JS · pytest

---

*Built as a portfolio exploration of generative multi-agent systems: realistic adversarial chaos engineering, durable AI-authored remediation, live observability with AI-blind overlays, and durable session-export tooling for analyzing agent behavior end-to-end.*
