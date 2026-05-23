import pytest

import llm
from restore import restore_all
from state import EventBus


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
        llm,
        "_make_client",
        lambda: FakeClient([FakeResp([FakeBlock("final", {"ok": True})])]),
    )
    out = llm._anthropic_tool_loop("sys", "usr", [], lambda n, i: {}, "final")
    assert out == {"ok": True}


def test_ai_chaos_writes_one_file_and_emits_damage(monkeypatch):
    from agents.chaos_agent import run_chaos
    from config import DATA_FILE

    new_data = '[{"temperature": 72, "city": "Denver"}]'
    script = [
        FakeResp([FakeBlock("read_data", {})]),
        FakeResp(
            [
                FakeBlock(
                    "sabotage_file",
                    {
                        "path": "data/weather_source.json",
                        "content": new_data,
                        "note": "renamed temp->temperature",
                    },
                )
            ]
        ),
        FakeResp([FakeBlock("done", {})]),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    run_chaos(bus)
    assert DATA_FILE.read_text() == new_data
    changed = [e for e in bus.events if e["type"] == "FILE_CHANGED"]
    assert len(changed) == 1
    assert changed[0]["data"]["kind"] == "damage"
    assert changed[0]["data"]["after"] == new_data
    # the viewer payload carries only path/kind/before/after — no chaos intent
    assert set(changed[0]["data"]) == {"path", "kind", "before", "after"}


def test_ai_chaos_rejects_non_whitelisted_path(monkeypatch):
    import pathlib

    from agents.chaos_agent import run_chaos

    script = [
        FakeResp(
            [
                FakeBlock(
                    "sabotage_file",
                    {"path": "llm.py", "content": "x=1", "note": "n"},
                )
            ]
        ),
        FakeResp([FakeBlock("done", {})]),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    run_chaos(bus)  # must not raise, must not write
    assert "x=1" not in pathlib.Path("llm.py").read_text()


def test_ai_chaos_rejects_emptying_the_data(monkeypatch):
    from agents.chaos_agent import run_chaos
    from config import DATA_FILE

    original = DATA_FILE.read_text()
    script = [
        FakeResp(
            [
                FakeBlock(
                    "sabotage_file",
                    {
                        "path": "data/weather_source.json",
                        "content": "[]",
                        "note": "wipe the feed",
                    },
                )
            ]
        ),
        FakeResp([FakeBlock("done", {})]),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    run_chaos(bus)
    assert DATA_FILE.read_text() == original  # guard refused the empty write


def test_ai_chaos_refuses_to_grow_row_count(monkeypatch):
    """Chaos may drift/corrupt/drop records but not resurrect dropped ones."""
    import json as _json

    from agents.chaos_agent import run_chaos
    from config import DATA_FILE

    # simulate a prior incident having dropped data down to 5 records
    current = _json.loads(DATA_FILE.read_text())[:5]
    DATA_FILE.write_text(_json.dumps(current))
    inflated = _json.dumps(current + [{"city": "X", "station_id": "Y", "temp": 0,
                                        "humidity": 0, "conditions": "clear",
                                        "wind_speed": 0, "wind_direction": "N",
                                        "pressure": 1000, "precipitation": 0,
                                        "timestamp": "2026-05-17T00:00:00"}] * 20)
    script = [
        FakeResp([FakeBlock("sabotage_file", {
            "path": "data/weather_source.json",
            "content": inflated, "note": "fabricate rows"})]),
        FakeResp([FakeBlock("done", {})]),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    before = DATA_FILE.read_text()
    run_chaos(bus)
    assert DATA_FILE.read_text() == before  # guard refused row inflation


def test_ai_chaos_rejects_pipeline_edit(monkeypatch):
    from agents.chaos_agent import run_chaos
    from config import PIPELINE_FILE

    original = PIPELINE_FILE.read_text()
    script = [
        FakeResp(
            [
                FakeBlock(
                    "sabotage_file",
                    {
                        "path": "pipeline.py",
                        "content": "def run(): pass",
                        "note": "introduce a bug",
                    },
                )
            ]
        ),
        FakeResp([FakeBlock("done", {})]),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    run_chaos(bus)
    assert PIPELINE_FILE.read_text() == original  # guard refused code edit


def test_ai_patch_refuses_to_fabricate_records(monkeypatch):
    import json as _json

    from agents import patch_agent
    from config import DATA_FILE

    # current data has 20 records (baseline); patch must not grow that.
    fabricated = _json.dumps([{"city": "X", "temp": 0, "humidity": 0,
                                "timestamp": "2026-01-01T00:00:00"}] * 30)
    script = [
        FakeResp([FakeBlock("write_file", {"path": "data/weather_source.json",
                                            "content": fabricated})]),
        FakeResp([FakeBlock("submit_patch", {"summary": "tried to fabricate"})]),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    before = DATA_FILE.read_text()
    patch_agent.run(
        bus,
        {"failure_type": "x", "confidence": 0.9, "reasoning": "r", "suggested_fix": "f"},
    )
    assert DATA_FILE.read_text() == before  # guard refused row inflation


def test_ai_patch_refuses_data_rewrite_when_current_unparseable(monkeypatch):
    from agents import patch_agent
    from config import DATA_FILE

    DATA_FILE.write_text("this is not json")
    script = [
        FakeResp([FakeBlock("write_file", {"path": "data/weather_source.json",
                                            "content": "[]"})]),
        FakeResp([FakeBlock("submit_patch", {"summary": "tried to rewrite"})]),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    patch_agent.run(
        bus,
        {"failure_type": "x", "confidence": 0.9, "reasoning": "r", "suggested_fix": "f"},
    )
    # data is still the garbage chaos created — patch refused to fabricate over it
    assert DATA_FILE.read_text() == "this is not json"


def test_ai_diagnose_returns_freeform_shape(monkeypatch):
    script = [
        FakeResp([FakeBlock("read_data", {})]),
        FakeResp(
            [
                FakeBlock(
                    "submit_diagnosis",
                    {
                        "failure_type": "schema keys renamed",
                        "confidence": 0.9,
                        "reasoning": "temp->temperature",
                        "suggested_fix": "read both keys",
                    },
                )
            ]
        ),
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
        FakeResp([FakeBlock("write_file", {"path": "pipeline.py", "content": good})]),
        FakeResp([FakeBlock("submit_patch", {"summary": "rewrote transform"})]),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    res = patch_agent.run(
        bus,
        {"failure_type": "x", "confidence": 0.9, "reasoning": "r", "suggested_fix": "f"},
    )
    assert res["fix"]
    heals = [
        e
        for e in bus.events
        if e["type"] == "FILE_CHANGED" and e["data"]["kind"] == "heal"
    ]
    assert len(heals) == 1


def test_ai_validator_judges(monkeypatch):
    from agents import validator_agent

    script = [
        FakeResp(
            [
                FakeBlock(
                    "submit_judgment",
                    {"passed": True, "reasoning": "clean 20-row table"},
                )
            ]
        )
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    bus = EventBus()
    assert validator_agent.run(bus) is True


def test_ai_chain_retries_patch_once_then_escalates(monkeypatch):
    from agents import monitor_agent

    calls = {"patch": 0, "validate": 0}
    monkeypatch.setattr(
        "agents.diagnosis_agent.diagnose",
        lambda e: {
            "failure_type": "x",
            "confidence": 0.9,
            "reasoning": "r",
            "suggested_fix": "f",
        },
    )

    def fake_patch(bus, diag, feedback=None):
        calls["patch"] += 1
        bus.emit("patch", "validator", "PATCH_APPLIED", "tried")
        return {"fix": "tried"}

    monkeypatch.setattr("agents.patch_agent.run", fake_patch)

    def fake_validate(bus):
        calls["validate"] += 1
        return False  # always fails

    monkeypatch.setattr("agents.validator_agent.run", fake_validate)
    bus = EventBus()
    monitor_agent._run_chain(bus, "err")
    assert calls["patch"] == 2  # original + one retry
    closed = [e for e in bus.events if e["type"] == "INCIDENT_CLOSED"][0]
    assert closed["data"]["resolved"] is False


def test_read_tools_never_leak_attribution(monkeypatch):
    seen = []
    real_loop = llm._anthropic_tool_loop

    def spy_loop(system, user, tools, executor, final_tool, max_turns=8):
        def wrapped(n, i):
            r = executor(n, i)
            seen.append(r)
            return r

        return real_loop(system, user, tools, wrapped, final_tool, max_turns)

    monkeypatch.setattr(llm, "_anthropic_tool_loop", spy_loop)
    script = [
        FakeResp([FakeBlock("read_data", {})]),
        FakeResp(
            [
                FakeBlock(
                    "submit_diagnosis",
                    {
                        "failure_type": "x",
                        "confidence": 0.9,
                        "reasoning": "r",
                        "suggested_fix": "f",
                    },
                )
            ]
        ),
    ]
    monkeypatch.setattr("llm._make_client", lambda: FakeClient(script))
    llm.diagnose("err")
    blob = str(seen)
    for forbidden in ("kind", "damage", "heal", "#ff2d55", "color"):
        assert forbidden not in blob
