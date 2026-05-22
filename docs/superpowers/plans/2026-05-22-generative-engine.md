# Generative Self-Healing Engine Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI mode fully generative — creative chaos, free-form diagnosis, generated patches, AI-judge validation, no enums or hardcoded heals — and emit an attributed `FILE_CHANGED` event stream the AI is blind to.

**Architecture:** Each AI agent runs a Claude tool-use loop (reusing `llm._anthropic_tool_loop`) with read/write/dry-run tools. All file mutations (mock and AI) route through one instrumented emitter that publishes `FILE_CHANGED{path,agent,kind,before,after}` to the EventBus. The pipeline runs in a timeout-bounded subprocess. Mock mode keeps its deterministic path.

**Tech Stack:** Python 3.12, FastAPI, APScheduler, anthropic SDK, pytest. AI agent tests use a stubbed Anthropic client (no live API).

---

## File Structure

- `tools/file_events.py` (new) — `emit_file_change()` low-level emitter + `track_changes()` context manager + writable-file whitelist. One responsibility: attributed file mutation.
- `tools/pipeline_tools.py` (modify) — `run_pipeline()` becomes subprocess+timeout; add `_pipeline_subprocess_result()`.
- `tools/schemas.py` (modify) — replace patch tools with generative read/write/dry-run/submit tool set; add chaos/diagnosis/validator tool sets.
- `llm.py` (modify) — add AI branches: `decide_sabotage`→creative, `diagnose`→free-form, new `generate_patch()` and `judge_output()`. Mock branches untouched.
- `agents/chaos_agent.py` (modify) — AI branch routes through `track_changes(kind="damage")`; mock branch wrapped in `track_changes` too.
- `agents/patch_agent.py` (modify) — AI branch = generative loop (`kind="heal"`); mock branch wrapped in `track_changes`.
- `agents/diagnosis_agent.py` (modify) — pass free-form diag through unchanged shape.
- `agents/validator_agent.py` (modify) — AI branch calls `judge_output()`.
- `agents/monitor_agent.py` (modify) — patch retry-once with validator feedback in AI mode.
- `agents/reporter_agent.py` (modify) — emit `FILE_CHANGED{kind:"restore"}` on baseline reset.
- `config.py` (modify) — add `WRITABLE_FILES`, `PIPELINE_TIMEOUT_SEC`.
- Tests: `tests/test_file_events.py` (new), `tests/test_subprocess_pipeline.py` (new), `tests/test_ai_agents.py` (new), updates to `tests/test_chaos.py`.

---

### Task 1: File-change emitter + whitelist

**Files:**
- Create: `tools/file_events.py`
- Modify: `config.py` (add `WRITABLE_FILES`)
- Test: `tests/test_file_events.py`

- [ ] **Step 1: Add config**

In `config.py`, after `PIPELINE_FILE = ...` line, add:

```python
WRITABLE_FILES = {DATA_FILE, PIPELINE_FILE}  # only files agents may mutate
PIPELINE_TIMEOUT_SEC = 10
```

- [ ] **Step 2: Write the failing test**

`tests/test_file_events.py`:

```python
import pytest

from config import DATA_FILE, PIPELINE_FILE, ROOT
from restore import restore_all
from state import EventBus
from tools.file_events import emit_file_change, track_changes


@pytest.fixture(autouse=True)
def clean():
    restore_all()
    yield
    restore_all()


def test_emit_file_change_publishes_event_with_attribution():
    bus = EventBus()
    emit_file_change(bus, "chaos", "damage", DATA_FILE, "before", "after")
    ev = bus.events[-1]
    assert ev["type"] == "FILE_CHANGED"
    assert ev["from_agent"] == "chaos"
    assert ev["data"]["kind"] == "damage"
    assert ev["data"]["before"] == "before"
    assert ev["data"]["after"] == "after"
    # path is project-relative for the UI
    assert ev["data"]["path"] == "data/weather_source.json"


def test_track_changes_emits_only_for_files_that_changed():
    bus = EventBus()
    with track_changes(bus, "patch", "heal", [DATA_FILE, PIPELINE_FILE]):
        DATA_FILE.write_text("mutated")
        # pipeline.py left untouched
    changed = [e for e in bus.events if e["type"] == "FILE_CHANGED"]
    assert len(changed) == 1
    assert changed[0]["data"]["path"] == "data/weather_source.json"
    assert changed[0]["data"]["after"] == "mutated"


def test_track_changes_rejects_non_whitelisted_path(tmp_path):
    bus = EventBus()
    outside = ROOT / "llm.py"
    with pytest.raises(ValueError):
        with track_changes(bus, "chaos", "damage", [outside]):
            pass
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_file_events.py -v`
Expected: FAIL — `ModuleNotFoundError: tools.file_events`

- [ ] **Step 4: Implement `tools/file_events.py`**

```python
"""Attributed file-mutation tracking for the dashboard's file viewer.

Every working-file mutation (chaos damage, patch heal, reporter restore) flows
through here so a FILE_CHANGED event is published with who changed it and how.
The AI agents NEVER receive these events — they only read raw file text. This
is a human-only overlay, like the baseline: harness ground truth the model can't
see.
"""

from contextlib import contextmanager

from config import ROOT, WRITABLE_FILES


def _rel(path):
    return str(path.resolve().relative_to(ROOT.resolve()))


def _check_writable(path):
    if path.resolve() not in {p.resolve() for p in WRITABLE_FILES}:
        raise ValueError(f"path not writable by agents: {path}")


def emit_file_change(bus, agent, kind, path, before, after):
    """Publish a FILE_CHANGED event. kind in {damage, heal, restore}."""
    bus.emit(
        agent,
        "viewer",
        "FILE_CHANGED",
        f"{agent} {kind} {_rel(path)}",
        {"path": _rel(path), "kind": kind, "before": before, "after": after},
    )


@contextmanager
def track_changes(bus, agent, kind, paths):
    """Snapshot `paths` before a mutation, emit FILE_CHANGED for each that
    actually changed afterward. Rejects non-whitelisted paths up front."""
    for p in paths:
        _check_writable(p)
    before = {p: (p.read_text() if p.exists() else None) for p in paths}
    yield
    for p in paths:
        after = p.read_text() if p.exists() else None
        if after != before[p]:
            emit_file_change(bus, agent, kind, p, before[p], after)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_file_events.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add tools/file_events.py tests/test_file_events.py config.py
git commit -m "feat: attributed FILE_CHANGED emitter + writable-file whitelist"
```

---

### Task 2: Subprocess-isolated pipeline runner

**Files:**
- Modify: `tools/pipeline_tools.py`
- Test: `tests/test_subprocess_pipeline.py`

- [ ] **Step 1: Write the failing test**

`tests/test_subprocess_pipeline.py`:

```python
import pytest

from config import PIPELINE_FILE
from restore import restore_all
from tools.pipeline_tools import run_pipeline


@pytest.fixture(autouse=True)
def clean():
    restore_all()
    yield
    restore_all()


def test_run_pipeline_returns_success_on_baseline():
    r = run_pipeline()
    assert r["success"] is True
    assert r["rows_processed"] == 20


def test_run_pipeline_times_out_on_infinite_loop():
    PIPELINE_FILE.write_text("import time\n\ndef run():\n    time.sleep(60)\n")
    r = run_pipeline()
    assert r["success"] is False
    assert r["error_type"] == "Timeout"


def test_run_pipeline_surfaces_syntax_error_as_result():
    PIPELINE_FILE.write_text("def run(:\n    pass\n")  # invalid syntax
    r = run_pipeline()
    assert r["success"] is False
    assert r["rows_processed"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_subprocess_pipeline.py -v`
Expected: FAIL — current in-process `run_pipeline` raises on bad syntax / hangs on the loop instead of returning a Timeout result.

- [ ] **Step 3: Rewrite `tools/pipeline_tools.py`**

```python
import json
import subprocess
import sys

from config import OUTPUT_FILE, PIPELINE_TIMEOUT_SEC, ROOT

# Run pipeline.run() in a fresh subprocess so AI-generated code (possible
# infinite loops, syntax errors, crashes) can never wedge the server. The
# subprocess prints the result dict as a single JSON line on stdout.
_RUNNER = (
    "import json,sys\n"
    "try:\n"
    "    import pipeline\n"
    "    print('PGRESULT'+json.dumps(pipeline.run()))\n"
    "except Exception as e:\n"
    "    print('PGRESULT'+json.dumps({'success':False,'rows_processed':0,"
    "'error':str(e),'error_type':type(e).__name__}))\n"
)


def _fail(error, error_type):
    return {"success": False, "rows_processed": 0, "error": error, "error_type": error_type}


def run_pipeline():
    """Execute pipeline.run() in a timeout-bounded subprocess; return its result."""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _RUNNER],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=PIPELINE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return _fail(f"pipeline exceeded {PIPELINE_TIMEOUT_SEC}s", "Timeout")
    for line in proc.stdout.splitlines():
        if line.startswith("PGRESULT"):
            return json.loads(line[len("PGRESULT"):])
    return _fail(proc.stderr.strip() or "no result emitted", "RunnerError")


def dry_run_pipeline():
    """Run the pipeline and return the structured result (used by agents to
    test a candidate fix). Output file is overwritten; validator re-runs anyway."""
    return run_pipeline()


def get_last_output():
    if not OUTPUT_FILE.exists():
        return None
    return json.loads(OUTPUT_FILE.read_text())
```

Note: `restore_data_file` and `rewrite_pipeline_section` are intentionally removed (the AI path no longer uses them; mock patch keeps its own helpers — see Task 5 note). If the mock `patch_agent` still imports them, keep thin shims OR (preferred) update the mock patch to use `restore.restore_data_only` directly and an inline str-replace. Verify with: `grep -rn "rewrite_pipeline_section\|restore_data_file" agents/ tools/` and reconcile in this task.

- [ ] **Step 4: Reconcile mock patch imports**

Run: `grep -rn "rewrite_pipeline_section\|restore_data_file" agents/`
For each hit in `agents/patch_agent.py` mock path, replace with local helpers:

```python
from restore import restore_data_only
from config import PIPELINE_FILE

def _mock_restore_data():
    restore_data_only()

def _mock_rewrite(old, new):
    src = PIPELINE_FILE.read_text()
    if old not in src:
        raise ValueError("old_code not found in pipeline.py")
    PIPELINE_FILE.write_text(src.replace(old, new, 1))
```

(Use these in `_apply_fix` instead of the removed tool functions.)

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_subprocess_pipeline.py tests/test_healing_chain.py -v`
Expected: PASS — subprocess tests pass AND the mock healing chain still resolves all 7 sabotages (it now runs the pipeline via subprocess).

- [ ] **Step 6: Commit**

```bash
git add tools/pipeline_tools.py agents/patch_agent.py tests/test_subprocess_pipeline.py
git commit -m "feat: run pipeline in timeout-bounded subprocess; isolate generated code"
```

---

### Task 3: Stubbable Anthropic client

**Files:**
- Modify: `llm.py`
- Test: `tests/test_ai_agents.py` (created here, extended later)

The AI-agent tasks need to drive `_anthropic_tool_loop` without a live API. Introduce a seam: a module-level client factory that tests monkeypatch.

- [ ] **Step 1: Write the failing test**

`tests/test_ai_agents.py`:

```python
import pytest

import llm
from restore import restore_all


class FakeBlock:
    def __init__(self, name, inp, btype="tool_use", id="b1"):
        self.type = btype
        self.name = name
        self.input = inp
        self.id = id


class FakeResp:
    def __init__(self, content):
        self.content = content


class FakeClient:
    """Scripts a sequence of model responses for the tool loop."""
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.messages = self

    def create(self, **_):
        return self._scripted.pop(0)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr("llm.USE_REAL", True)
    restore_all()
    yield
    restore_all()


def test_anthropic_loop_uses_injected_client(monkeypatch):
    monkeypatch.setattr(
        llm, "_make_client",
        lambda: FakeClient([FakeResp([FakeBlock("final", {"ok": True})])]),
    )
    out = llm._anthropic_tool_loop("sys", "usr", [], lambda n, i: {}, "final")
    assert out == {"ok": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ai_agents.py::test_anthropic_loop_uses_injected_client -v`
Expected: FAIL — `llm._make_client` does not exist.

- [ ] **Step 3: Add the client seam in `llm.py`**

Replace the `import anthropic` / `client = anthropic.Anthropic()` inside `_anthropic_tool_loop` with a module-level factory:

```python
def _make_client():
    import anthropic
    return anthropic.Anthropic()
```

And in `_anthropic_tool_loop`, change the first lines to:

```python
def _anthropic_tool_loop(system, user, tools, tool_executor, final_tool, max_turns=8):
    client = _make_client()
    messages = [{"role": "user", "content": user}]
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ai_agents.py::test_anthropic_loop_uses_injected_client -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm.py tests/test_ai_agents.py
git commit -m "refactor: inject Anthropic client via _make_client seam for testability"
```

---

### Task 4: Creative chaos (AI branch)

**Files:**
- Modify: `llm.py` (`decide_sabotage` → add creative generation `generate_sabotage`), `tools/schemas.py` (chaos tools), `agents/chaos_agent.py`
- Test: `tests/test_ai_agents.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ai_agents.py`:

```python
from agents.chaos_agent import run_chaos
from config import DATA_FILE
from state import EventBus
from tests.test_ai_agents import FakeBlock, FakeResp, FakeClient  # noqa (same module)


def test_ai_chaos_writes_one_file_and_emits_damage(monkeypatch):
    new_data = '[{"temperature": 72, "city": "Denver"}]'
    script = [
        FakeResp([FakeBlock("read_data", {})]),
        FakeResp([FakeBlock(
            "sabotage_file",
            {"path": "data/weather_source.json", "content": new_data,
             "note": "renamed temp->temperature"},
        )]),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    run_chaos(bus)
    assert DATA_FILE.read_text() == new_data
    changed = [e for e in bus.events if e["type"] == "FILE_CHANGED"]
    assert len(changed) == 1
    assert changed[0]["data"]["kind"] == "damage"
    # the chaos note must NOT appear in any read-tool output the model saw
    assert "renamed temp" not in str([e for e in bus.events if e["type"] != "FILE_CHANGED"])


def test_ai_chaos_rejects_non_whitelisted_path(monkeypatch):
    script = [FakeResp([FakeBlock(
        "sabotage_file",
        {"path": "llm.py", "content": "x=1", "note": "n"})])]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    run_chaos(bus)  # must not raise, must not write
    import pathlib
    assert "x=1" not in pathlib.Path("llm.py").read_text()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_ai_agents.py -k chaos -v`
Expected: FAIL — AI branch not implemented.

- [ ] **Step 3: Add chaos tools to `tools/schemas.py`**

```python
READ_TOOLS = [
    {"name": "read_data", "description": "Read the raw data source file text.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "read_pipeline", "description": "Read the raw pipeline.py source.",
     "input_schema": {"type": "object", "properties": {}}},
]

CHAOS_TOOLS = READ_TOOLS + [
    {"name": "sabotage_file",
     "description": "Write a small breaking change to ONE file "
                    "(data/weather_source.json or pipeline.py).",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"},
         "note": {"type": "string"}}, "required": ["path", "content", "note"]}},
]
```

- [ ] **Step 4: Implement `generate_sabotage` in `llm.py`**

```python
from config import DATA_FILE, PIPELINE_FILE
from tools.schemas import CHAOS_TOOLS

def _read_tool(name):
    if name == "read_data":
        return DATA_FILE.read_text() if DATA_FILE.exists() else "<missing>"
    if name == "read_pipeline":
        return PIPELINE_FILE.read_text()
    return {"error": "unknown tool"}

def generate_sabotage(write_fn):
    """Drive Claude to invent ONE breaking change. `write_fn(path, content)`
    performs the (whitelisted, attributed) write and returns a plain string.
    Returns the model's free-text note."""
    captured = {"note": ""}

    def executor(name, inp):
        if name == "sabotage_file":
            captured["note"] = inp.get("note", "")
            return write_fn(inp["path"], inp["content"])  # plain string only
        return _read_tool(name)

    # sabotage_file IS the terminal tool: loop ends when the model calls it.
    llm_out = _anthropic_tool_loop(
        "You are a chaos engineering agent attacking a weather ETL. Inspect the "
        "data and pipeline, then introduce ONE small, plausible breaking change "
        "to exactly ONE file via sabotage_file. Keep it subtle and realistic.",
        "Investigate, then sabotage one file.",
        CHAOS_TOOLS, executor, final_tool="sabotage_file",
    )
    # _anthropic_tool_loop returns the final tool's input; note already captured
    return captured["note"]
```

Note: the loop's `final_tool` returns its input dict — but we must still perform the write. Adjust `_anthropic_tool_loop` so the final tool is ALSO passed to `tool_executor` before returning. Simplest: in chaos, do not mark `sabotage_file` as `final_tool`; instead let executor perform the write and signal completion by returning, then add an explicit terminal `done` tool. **Implementation choice for this plan:** add a no-arg `done` tool to `CHAOS_TOOLS` and set `final_tool="done"`; the model calls `sabotage_file` (executed, writes) then `done`. Update the test scripts to append `FakeResp([FakeBlock("done", {})])`.

Revise CHAOS_TOOLS to append:
```python
    {"name": "done", "description": "Call when the sabotage is complete.",
     "input_schema": {"type": "object", "properties": {}}},
```
And test scripts get a trailing `FakeResp([FakeBlock("done", {})])`.

- [ ] **Step 5: Rewrite `agents/chaos_agent.py` AI branch**

Keep the mock branch but wrap its mutation in `track_changes`. Add the AI branch:

```python
import llm
from config import DATA_FILE, PIPELINE_FILE, WRITABLE_FILES
from tools.file_events import emit_file_change, track_changes

def _ai_chaos(bus):
    def write_fn(path_str, content):
        target = next((p for p in WRITABLE_FILES
                       if str(p).endswith(path_str)), None)
        if target is None:
            return f"refused: {path_str} is not writable"
        before = target.read_text() if target.exists() else None
        target.write_text(content)
        emit_file_change(bus, "chaos", "damage", target, before, content)
        return f"wrote {len(content)} chars to {path_str}"
    note = llm.generate_sabotage(write_fn)
    bus.emit("chaos", "monitor", "SABOTAGE_APPLIED",
             f"Chaos applied a change ({note})", {"note": note})
    return note
```

And in `run_chaos`, branch:
```python
def run_chaos(bus):
    if bus.incident["active"]:
        return None
    if llm.USE_REAL:
        return _ai_chaos(bus)
    # ... existing mock path, but wrap the SABOTAGE_FNS call:
    sabotage = decide_sabotage(recent)
    bus.emit("chaos", "pipeline", "SABOTAGE_PLANNED", ...)
    with track_changes(bus, "chaos", "damage", [DATA_FILE, PIPELINE_FILE]):
        SABOTAGE_FNS[sabotage]()
    bus.last_sabotage = sabotage
    bus.emit("chaos", "monitor", "SABOTAGE_APPLIED", ...)
    return sabotage
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_ai_agents.py -k chaos tests/test_chaos.py -v`
Expected: chaos AI tests PASS. `test_chaos.py::test_run_chaos_emits_planned_then_applied` now FAILS (extra FILE_CHANGED event).

- [ ] **Step 7: Update `tests/test_chaos.py`**

Change the exact-sequence assertion to ignore FILE_CHANGED:

```python
    comms = [t for t in types if t != "FILE_CHANGED"]
    assert comms == ["SABOTAGE_PLANNED", "SABOTAGE_APPLIED"]
```

- [ ] **Step 8: Run tests, then commit**

Run: `python -m pytest tests/test_ai_agents.py tests/test_chaos.py -v` → PASS

```bash
git add llm.py tools/schemas.py agents/chaos_agent.py tests/test_ai_agents.py tests/test_chaos.py
git commit -m "feat: creative AI chaos agent + route all chaos writes through FILE_CHANGED"
```

---

### Task 5: Free-form diagnosis + generative patch + AI-judge validator

**Files:**
- Modify: `llm.py` (`diagnose` AI branch free-form; add `generate_patch`, `judge_output`), `tools/schemas.py`, `agents/patch_agent.py`, `agents/validator_agent.py`
- Test: `tests/test_ai_agents.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_ai_diagnose_returns_freeform_shape(monkeypatch):
    script = [
        FakeResp([FakeBlock("read_data", {})]),
        FakeResp([FakeBlock("submit_diagnosis", {
            "failure_type": "schema keys renamed",
            "confidence": 0.9, "reasoning": "temp->temperature",
            "suggested_fix": "read both keys"})]),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    d = llm.diagnose("KeyError: temp")
    assert d["confidence"] == 0.9
    assert d["failure_type"] == "schema keys renamed"  # free text, not enum


def test_ai_patch_writes_heal_via_track(monkeypatch):
    from agents import patch_agent
    from config import PIPELINE_FILE
    good = PIPELINE_FILE.read_text()
    script = [
        FakeResp([FakeBlock("read_pipeline", {})]),
        FakeResp([FakeBlock("write_file", {
            "path": "pipeline.py", "content": good})]),
        FakeResp([FakeBlock("submit_patch", {"summary": "rewrote transform"})]),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    res = patch_agent.run(bus, {"failure_type": "x", "confidence": 0.9,
                                "reasoning": "r", "suggested_fix": "f"})
    assert res["fix"]
    heals = [e for e in bus.events
             if e["type"] == "FILE_CHANGED" and e["data"]["kind"] == "heal"]
    assert len(heals) == 1


def test_ai_validator_judges(monkeypatch):
    from agents import validator_agent
    script = [FakeResp([FakeBlock("submit_judgment",
              {"passed": True, "reasoning": "clean 20-row table"})])]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    assert validator_agent.run(bus) is True
```

- [ ] **Step 2: Run to verify failures**

Run: `python -m pytest tests/test_ai_agents.py -k "diagnose or patch or validator" -v`
Expected: FAIL — AI branches not implemented.

- [ ] **Step 3: Add tool schemas** (`tools/schemas.py`)

```python
WRITE_TOOLS = READ_TOOLS + [
    {"name": "write_file", "description": "Write full new content to "
     "data/weather_source.json or pipeline.py.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["path", "content"]}},
    {"name": "dry_run", "description": "Run the pipeline and see the result.",
     "input_schema": {"type": "object", "properties": {}}},
]

PATCH_TOOLS = WRITE_TOOLS + [
    {"name": "submit_patch", "description": "Report the fix applied.",
     "input_schema": {"type": "object", "properties": {
         "summary": {"type": "string"}}, "required": ["summary"]}},
]

DIAGNOSE_TOOLS = READ_TOOLS + [
    {"name": "submit_diagnosis", "description": "Submit free-form root cause.",
     "input_schema": {"type": "object", "properties": {
         "failure_type": {"type": "string"}, "confidence": {"type": "number"},
         "reasoning": {"type": "string"}, "suggested_fix": {"type": "string"}},
         "required": ["failure_type", "confidence", "reasoning", "suggested_fix"]}},
]

VALIDATE_TOOLS = READ_TOOLS + [
    {"name": "run_output", "description": "Run pipeline and read its output.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "submit_judgment", "description": "Judge if output is clean data.",
     "input_schema": {"type": "object", "properties": {
         "passed": {"type": "boolean"}, "reasoning": {"type": "string"}},
         "required": ["passed", "reasoning"]}},
]
```

- [ ] **Step 4: Implement `llm.diagnose` AI branch, `generate_patch`, `judge_output`**

Replace the AI branch of `diagnose` to use `DIAGNOSE_TOOLS` with an executor wired to `_read_tool` and return the `submit_diagnosis` input verbatim (free-form `failure_type`). Then add:

```python
from tools.schemas import PATCH_TOOLS, VALIDATE_TOOLS
from tools.pipeline_tools import dry_run_pipeline, get_last_output

def generate_patch(diag, write_fn, feedback=None):
    """Drive Claude to read files and write a fix. `write_fn(path, content)`
    performs the attributed heal write. Returns {"summary": str}."""
    def executor(name, inp):
        if name == "write_file":
            return write_fn(inp["path"], inp["content"])
        if name == "dry_run":
            return dry_run_pipeline()
        return _read_tool(name)
    extra = f"\nA previous attempt failed validation: {feedback}" if feedback else ""
    return _anthropic_tool_loop(
        "You repair a broken weather ETL. Read the data and pipeline, find the "
        "fault, and WRITE a fix (to the data and/or pipeline.py) so the pipeline "
        "produces clean, consistent rows. You may dry_run to check. Do not assume "
        "any reference/baseline exists." + extra,
        f"Diagnosis: {diag['reasoning']}. Fix it, then submit_patch.",
        PATCH_TOOLS, executor, final_tool="submit_patch",
    )

def judge_output():
    def executor(name, inp):
        if name == "run_output":
            return {"result": dry_run_pipeline(), "output": get_last_output()}
        return _read_tool(name)
    return _anthropic_tool_loop(
        "You validate a weather ETL's output. Run it, then judge whether the "
        "output is clean, internally-consistent data (uniform keys, consistent "
        "types, sane row count, no nulls). Submit your judgment.",
        "Validate the current pipeline output.",
        VALIDATE_TOOLS, executor, final_tool="submit_judgment",
    )
```

- [ ] **Step 5: Patch agent AI branch** (`agents/patch_agent.py`)

```python
def _ai_patch(bus, diag, feedback=None):
    from config import WRITABLE_FILES
    from tools.file_events import emit_file_change

    def write_fn(path_str, content):
        target = next((p for p in WRITABLE_FILES if str(p).endswith(path_str)), None)
        if target is None:
            return f"refused: {path_str} not writable"
        before = target.read_text() if target.exists() else None
        target.write_text(content)
        emit_file_change(bus, "patch", "heal", target, before, content)
        return f"wrote {len(content)} chars to {path_str}"

    out = llm.generate_patch(diag, write_fn, feedback)
    summary = out.get("summary", "patch applied")
    bus.emit("patch", "validator", "PATCH_APPLIED", summary, {"fix": summary})
    return {"fix": summary}
```

In `run`, branch at the top: `if llm.USE_REAL: return _ai_patch(bus, diag)` (after the confidence gate, which stays). Mock branch wraps `_apply_fix` in `track_changes(bus, "patch", "heal", [DATA_FILE, PIPELINE_FILE])`.

- [ ] **Step 6: Validator AI branch** (`agents/validator_agent.py`)

```python
import llm

def run(bus):
    bus.emit("validator", "patch", "VALIDATION_STARTED", "Re-running pipeline")
    if llm.USE_REAL:
        out = llm.judge_output()
        ok = bool(out.get("passed"))
        ev = "VALIDATION_PASSED" if ok else "VALIDATION_FAILED"
        bus.emit("validator", "reporter", ev, out.get("reasoning", ""), out)
        if not ok:
            bus.emit("validator", "system", "ESCALATE", "Fix did not resolve.")
        return ok
    # ... existing deterministic mock branch unchanged ...
```

- [ ] **Step 7: Run tests, commit**

Run: `python -m pytest tests/test_ai_agents.py tests/test_healing_chain.py -v` → PASS

```bash
git add llm.py tools/schemas.py agents/patch_agent.py agents/validator_agent.py tests/test_ai_agents.py
git commit -m "feat: free-form diagnosis, generative patch, AI-judge validator"
```

---

### Task 6: Patch retry-once + reporter restore event

**Files:**
- Modify: `agents/monitor_agent.py`, `agents/reporter_agent.py`
- Test: `tests/test_ai_agents.py`

- [ ] **Step 1: Write the failing test**

```python
def test_ai_chain_retries_patch_once_then_escalates(monkeypatch):
    import llm
    from agents import monitor_agent
    from state import EventBus
    calls = {"patch": 0, "validate": 0}
    monkeypatch.setattr("agents.diagnosis_agent.diagnose",
        lambda e: {"failure_type": "x", "confidence": 0.9,
                   "reasoning": "r", "suggested_fix": "f"})
    def fake_patch(bus, diag, feedback=None):
        calls["patch"] += 1
        bus.emit("patch", "validator", "PATCH_APPLIED", "tried")
        return {"fix": "tried"}
    monkeypatch.setattr("agents.patch_agent.run", fake_patch)
    def fake_validate(bus):
        calls["validate"] += 1
        return False  # always fails
    monkeypatch.setattr("agents.validator_agent.run", fake_validate)
    monkeypatch.setattr("llm.USE_REAL", True)
    bus = EventBus()
    monitor_agent._run_chain(bus, "err")
    assert calls["patch"] == 2   # original + one retry
    closed = [e for e in bus.events if e["type"] == "INCIDENT_CLOSED"][0]
    assert closed["data"]["resolved"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_ai_agents.py -k retries -v`
Expected: FAIL — no retry today (patch called once).

- [ ] **Step 3: Update `_run_chain` in `agents/monitor_agent.py`**

`patch_agent.run` must accept an optional `feedback` kwarg (add `feedback=None` to its signature; mock branch ignores it). Then:

```python
def _run_chain(bus, error):
    diag = diagnosis_agent.run(bus, error)
    if diag.get("escalated"):
        reporter_agent.run(bus, resolved=False, diag=diag, fix="none — escalated at diagnosis")
        return
    patch_res = patch_agent.run(bus, diag)
    if patch_res.get("escalated"):
        reporter_agent.run(bus, resolved=False, diag=diag, fix="none — escalated at patch")
        return
    passed = validator_agent.run(bus)
    if not passed and llm.USE_REAL:
        patch_res = patch_agent.run(bus, diag, feedback="previous fix failed validation")
        passed = validator_agent.run(bus)
    reporter_agent.run(bus, resolved=passed, diag=diag, fix=patch_res["fix"])
```

Add `import llm` at top of `monitor_agent.py`.

- [ ] **Step 4: Reporter emits restore event** (`agents/reporter_agent.py`)

Replace the trailing `restore_all()` with a tracked version:

```python
    from tools.file_events import emit_file_change
    from config import DATA_FILE, PIPELINE_FILE
    before = {p: (p.read_text() if p.exists() else None)
              for p in (DATA_FILE, PIPELINE_FILE)}
    restore_all()
    for p in (DATA_FILE, PIPELINE_FILE):
        after = p.read_text()
        if after != before[p]:
            emit_file_change(bus, "reporter", "restore", p, before[p], after)
```

- [ ] **Step 5: Run tests, commit**

Run: `python -m pytest tests/ -v` → ALL PASS

```bash
git add agents/monitor_agent.py agents/reporter_agent.py agents/patch_agent.py tests/test_ai_agents.py
git commit -m "feat: AI patch retry-once with validator feedback; reporter emits restore events"
```

---

### Task 7: Full regression + AI-blindness assertion

**Files:**
- Test: `tests/test_ai_agents.py`

- [ ] **Step 1: AI-blindness test**

```python
def test_read_tools_never_leak_attribution(monkeypatch):
    import llm
    seen = []
    real_loop = llm._anthropic_tool_loop
    # capture every tool_executor result the model would receive
    def spy_loop(system, user, tools, executor, final_tool, max_turns=8):
        def wrapped(n, i):
            r = executor(n, i)
            seen.append(r)
            return r
        return real_loop(system, user, tools, wrapped, final_tool, max_turns)
    monkeypatch.setattr(llm, "_anthropic_tool_loop", spy_loop)
    script = [FakeResp([FakeBlock("read_data", {})]),
              FakeResp([FakeBlock("submit_diagnosis", {
                  "failure_type": "x", "confidence": 0.9,
                  "reasoning": "r", "suggested_fix": "f"})])]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    llm.diagnose("err")
    blob = str(seen)
    for forbidden in ("kind", "damage", "heal", "#ff2d55", "color"):
        assert forbidden not in blob
```

- [ ] **Step 2: Run full suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS (mock path intact, AI path covered, AI blind to attribution).

- [ ] **Step 3: Commit**

```bash
git add tests/test_ai_agents.py
git commit -m "test: assert AI agents never receive file-change attribution"
```

---

## Self-Review Notes

- **Spec coverage:** creative chaos (T4), free-form diagnosis (T5), generative patch no-hardcoded-heal (T5), AI-judge validator (T5), FILE_CHANGED + AI-blindness (T1,T4,T5,T7), subprocess safety (T2), retry-once + escalate (T6), mock untouched (T2,T4 keep mock branches + tests). Phase 2/3 deferred.
- **Whitelist** enforced in `track_changes` (mock) and in each AI `write_fn` (refusal string, no raise — so a misbehaving model can't crash the chain).
- **Mock visualization:** mock chaos/patch now emit FILE_CHANGED via `track_changes`, so the Phase 2 viewer works without API spend.
