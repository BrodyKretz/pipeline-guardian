import json

import pytest

from agents.chaos_agent import SABOTAGE_FNS, run_chaos
from config import DATA_FILE, SABOTAGE_TYPES
from llm import _classify, inspect_data_state
from restore import restore_all
from state import EventBus


@pytest.fixture(autouse=True)
def clean():
    restore_all()
    yield
    restore_all()


@pytest.mark.parametrize("name", SABOTAGE_TYPES)
def test_each_sabotage_produces_its_signature(name):
    SABOTAGE_FNS[name]()
    detected, conf, _ = _classify(inspect_data_state())
    assert detected == name


def test_run_chaos_emits_planned_then_applied(monkeypatch):
    monkeypatch.setattr("llm.USE_REAL", False)
    bus = EventBus()
    sabotage = run_chaos(bus)
    assert sabotage in SABOTAGE_TYPES
    types = [e["type"] for e in bus.events]
    assert types == ["SABOTAGE_PLANNED", "SABOTAGE_APPLIED"]
    assert bus.events[0]["from_agent"] == "chaos"
    assert bus.events[0]["to_agent"] == "pipeline"
    assert bus.events[1]["to_agent"] == "monitor"
    assert bus.last_sabotage == sabotage


def test_run_chaos_noop_when_incident_active():
    bus = EventBus()
    bus.start_incident()
    assert run_chaos(bus) is None
    assert bus.events == []
