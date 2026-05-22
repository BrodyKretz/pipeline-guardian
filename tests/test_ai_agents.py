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
