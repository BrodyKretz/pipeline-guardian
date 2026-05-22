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
