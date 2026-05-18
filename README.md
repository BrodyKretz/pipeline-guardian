# 🛡️ Pipeline Guardian

**A multi-agent self-healing system: one agent sabotages a data pipeline, five
others detect, diagnose, repair, and verify the damage — with a live dashboard
to watch it happen.**

A **Chaos Agent** continuously sabotages an ETL pipeline. A **self-healing
chain** — Monitor → Diagnosis → Patch → Validator → Reporter — detects,
diagnoses, repairs, and verifies every break autonomously. A real-time
dashboard renders all six agents as nodes on a clock face with animated
messages flowing between them as they fight.

> **Read this before you judge the "AI" part — [Where the intelligence actually
> is](#where-the-intelligence-actually-is).** Short version: these are six
> agents in the *architectural* sense (bounded roles, isolated, communicating
> over an event bus). Only the **two** steps that require genuine judgment —
> Chaos's sabotage choice and Diagnosis's root-cause classification — call the
> Claude API, and only when a key is set. The other four are deterministic by
> design, because using an LLM where a rule is correct would be worse
> engineering. This is a deliberate decision, not a shortcut.

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

### Dashboard controls

The dashboard has a live control strip — no terminal needed:

- **▶ Start / ⏸ Pause / ⏹ Stop** — gate all automation (chaos *and* monitor).
  Pause freezes everything; Stop also clears any active incident and restores
  the baseline.
- **MOCK / AI toggle** — switch reasoning mode at runtime. Choosing **AI** with
  no key on file pops an inline field to paste an `ANTHROPIC_API_KEY`; it's
  merged into `.env` (git-ignored) and applied immediately.

### Mock mode vs. real Claude

- **No `ANTHROPIC_API_KEY`** → deterministic mock brain. The full system runs
  and self-heals. Diagnosis classifies from real observed signals only (it
  never peeks at which sabotage was applied), so the *choreography* is genuine
  even though no model is involved.
- **Valid `ANTHROPIC_API_KEY`** → the two judgment steps (Chaos's sabotage
  choice, Diagnosis's root-cause classification) reason through Claude
  (`claude-sonnet-4-6`) via tool use. Any API error degrades gracefully back to
  the mock path and the incident escalates rather than crashing.

---

## Where the intelligence actually is

Be clear-eyed about what this is, because "agent" is an overloaded word.

**These are six agents in the architectural sense** — six bounded roles, each
in its own module, isolated, communicating only through the event bus and
explicit handoffs. By the classical AI definition (perceive an environment,
act on it toward a goal) every one qualifies, no LLM required.

**Only two of them call an LLM, and only with a key set:**

| Agent | Uses Claude? | Why |
|---|---|---|
| Chaos | ✅ (with key) | *Judgment:* which sabotage is interesting given recent history |
| Diagnosis | ✅ (with key) | *Judgment:* infer root cause from observed signals |
| Monitor | ❌ | Run pipeline, check a boolean — deterministic |
| Patch | ❌ | Known failure type → known fix; a lookup, not a decision |
| Validator | ❌ | Re-run pipeline, assert row count + schema — deterministic |
| Reporter | ❌ | Write JSON / SQLite — deterministic |

This split is **deliberate, and it's the point**. Putting an LLM behind
Validator or Reporter would be slower, costlier, non-deterministic, and
strictly worse than the four lines of code that do the job correctly. The
intelligence sits exactly where genuine judgment is required and nowhere else.
Knowing when *not* to reach for a model is the senior decision here — most
LLM demos bolt one onto everything and become fragile for it.

So: a multi-agent orchestration with LLM-backed reasoning at its two decision
points — not "six autonomous AI minds," and it doesn't pretend to be.

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
tests/             pytest suite (56 tests)
```

## Testing

```bash
pytest -q     # 56 tests: pipeline, event bus, restore, mock brain, tools,
              # chaos, full healing-chain e2e (all 7 sabotages), API, controls
```

The end-to-end chain is fully verifiable in mock mode with no API key.

## Tech stack

Python 3.11+ · Claude API (tool use) · FastAPI · uvicorn · APScheduler ·
SQLite · WebSockets · vanilla HTML/CSS/JS · pytest

---

*Built as a portfolio project exploring autonomous multi-agent systems,
adversarial self-healing, and real-time agent observability.*
