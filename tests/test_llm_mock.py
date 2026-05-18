import json

import pytest

from config import BASELINE_DIR, DATA_FILE
from llm import decide_sabotage, diagnose, inspect_data_state
from restore import restore_all


def _records():
    return json.loads((BASELINE_DIR / "weather_source.json").read_text())


def _write(data):
    DATA_FILE.write_text(json.dumps(data))


@pytest.fixture(autouse=True)
def clean():
    restore_all()
    yield
    restore_all()


CASES = {
    "MISSING_FILE": lambda: DATA_FILE.unlink(),
    "EMPTY_DATA": lambda: _write([]),
    "SCHEMA_RENAME": lambda: _write(
        [{"temperature": r["temp"], "location": r["city"],
          "humidity": r["humidity"], "timestamp": r["timestamp"]}
         for r in _records()]
    ),
    "TYPE_CORRUPTION": lambda: _write(
        [{**r, "temp": f"{r['temp']}F"} for r in _records()]
    ),
    "NULL_INJECTION": lambda: _write(
        [{**r, "temp": None} if i % 3 == 0 else r
         for i, r in enumerate(_records())]
    ),
    "DATE_FORMAT": lambda: _write(
        [{**r, "timestamp": "05/17/2026 08:00"} for r in _records()]
    ),
    "DUPLICATE_ROWS": lambda: _write(_records() * 10),
}


@pytest.mark.parametrize("expected", list(CASES))
def test_mock_diagnose_classifies_each_signal(expected, monkeypatch):
    monkeypatch.setattr("llm.USE_REAL", False)
    CASES[expected]()
    d = diagnose("pipeline failed: synthetic error")
    assert d["failure_type"] == expected
    assert 0.0 <= d["confidence"] <= 1.0
    assert d["confidence"] >= 0.85
    assert d["reasoning"] and d["suggested_fix"]


def test_inspect_data_state_healthy():
    s = inspect_data_state()
    assert s["exists"] and s["is_list"]
    assert s["row_count"] == 20
    assert not s["temp_is_string"] and not s["has_null_temp"]
    assert s["timestamp_iso"]


def test_decide_sabotage_avoids_recent(monkeypatch):
    monkeypatch.setattr("llm.USE_REAL", False)
    recent = ["SCHEMA_RENAME", "TYPE_CORRUPTION"]
    picks = {decide_sabotage(recent) for _ in range(40)}
    assert picks  # returns something
    assert "SCHEMA_RENAME" not in picks and "TYPE_CORRUPTION" not in picks
