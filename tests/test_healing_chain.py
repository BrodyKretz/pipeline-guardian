import pytest

from agents import monitor_agent
from agents.chaos_agent import SABOTAGE_FNS
from config import BASELINE_DIR, DATA_FILE, PIPELINE_FILE, SABOTAGE_TYPES
from restore import restore_all
from state import EventBus


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr("llm.USE_REAL", False)
    restore_all()
    yield
    restore_all()


@pytest.mark.parametrize("sabotage", SABOTAGE_TYPES)
def test_full_chain_resolves_each_sabotage(sabotage):
    bus = EventBus()
    SABOTAGE_FNS[sabotage]()
    bus.last_sabotage = sabotage

    monitor_agent.tick(bus)

    types = [e["type"] for e in bus.events]
    assert "FAILURE_DETECTED" in types
    assert "DIAGNOSIS_COMPLETE" in types
    assert "PATCH_APPLIED" in types
    assert "VALIDATION_PASSED" in types, f"{sabotage} not resolved: {types}"
    assert "VALIDATION_FAILED" not in types

    closed = [e for e in bus.events if e["type"] == "INCIDENT_CLOSED"][0]
    assert closed["data"]["resolved"] is True

    diag = [e for e in bus.events if e["type"] == "DIAGNOSIS_COMPLETE"][0]
    assert diag["data"]["failure_type"] == sabotage

    # Incident closed and BOTH working files restored to baseline.
    assert bus.incident["active"] is False
    assert DATA_FILE.read_bytes() == (
        BASELINE_DIR / "weather_source.json"
    ).read_bytes()
    assert PIPELINE_FILE.read_bytes() == (BASELINE_DIR / "pipeline.py").read_bytes()


def test_healthy_pipeline_opens_no_incident():
    bus = EventBus()
    monitor_agent.tick(bus)
    types = [e["type"] for e in bus.events]
    assert types == ["PIPELINE_TRIGGERED", "PIPELINE_HEALTHY"]
    assert bus.incident["active"] is False


def test_low_confidence_escalates(monkeypatch):
    bus = EventBus()

    def fake_diagnose(_err):
        return {
            "failure_type": "UNKNOWN",
            "confidence": 0.2,
            "reasoning": "no idea",
            "suggested_fix": "human",
        }

    monkeypatch.setattr("agents.diagnosis_agent.diagnose", fake_diagnose)
    SABOTAGE_FNS["EMPTY_DATA"]()
    bus.last_sabotage = "EMPTY_DATA"
    monitor_agent.tick(bus)

    types = [e["type"] for e in bus.events]
    assert "ESCALATE" in types
    assert "PATCH_APPLIED" not in types
    closed = [e for e in bus.events if e["type"] == "INCIDENT_CLOSED"][0]
    assert closed["data"]["resolved"] is False
