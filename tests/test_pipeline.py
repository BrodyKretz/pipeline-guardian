import importlib
import json
import shutil

import pytest

from config import BASELINE_DIR, DATA_FILE, OUTPUT_FILE


def reset_data():
    shutil.copy(BASELINE_DIR / "weather_source.json", DATA_FILE)


def fresh_pipeline():
    import pipeline

    return importlib.reload(pipeline)


def test_healthy_run_succeeds():
    reset_data()
    r = fresh_pipeline().run()
    assert r["success"] is True
    assert r["rows_processed"] == 20
    assert r["error"] is None and r["error_type"] is None
    out = json.loads(OUTPUT_FILE.read_text())
    assert len(out) == 20
    assert isinstance(out[0]["temp"], float)
    assert set(out[0]) == {"city", "temp", "humidity", "timestamp"}


def _records():
    return json.loads((BASELINE_DIR / "weather_source.json").read_text())


def _write(data):
    DATA_FILE.write_text(json.dumps(data))


SABOTAGES = {
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
    "EMPTY_DATA": lambda: _write([]),
    "MISSING_FILE": lambda: DATA_FILE.unlink(),
    "DATE_FORMAT": lambda: _write(
        [{**r, "timestamp": "05/17/2026 08:00"} for r in _records()]
    ),
    "DUPLICATE_ROWS": lambda: _write(_records() * 10),
}


@pytest.mark.parametrize("name", list(SABOTAGES))
def test_sabotage_returns_structured_error_without_raising(name):
    reset_data()
    SABOTAGES[name]()
    r = fresh_pipeline().run()
    if name == "DUPLICATE_ROWS":
        # Pipeline still "succeeds" but the row count is anomalous (200).
        assert r["rows_processed"] == 200
    else:
        assert r["success"] is False
        assert r["error"] and r["error_type"]
    reset_data()
