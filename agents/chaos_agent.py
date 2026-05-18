"""Chaos Agent — deliberately sabotages the pipeline's data source."""

import json

from config import DATA_FILE
from llm import decide_sabotage
from tools.log_tools import read_incident_log


def _read():
    return json.loads(DATA_FILE.read_text())


def _write(data):
    DATA_FILE.write_text(json.dumps(data, indent=2))


def _schema_rename():
    _write(
        [
            {
                "temperature": r["temp"],
                "location": r["city"],
                "humidity": r["humidity"],
                "timestamp": r["timestamp"],
            }
            for r in _read()
        ]
    )


def _type_corruption():
    _write([{**r, "temp": f"{r['temp']}F"} for r in _read()])


def _null_injection():
    _write(
        [
            {**r, "temp": None} if i % 3 == 0 else r
            for i, r in enumerate(_read())
        ]
    )


def _empty_data():
    _write([])


def _missing_file():
    DATA_FILE.unlink(missing_ok=True)


def _date_format():
    _write([{**r, "timestamp": "05/17/2026 08:00"} for r in _read()])


def _duplicate_rows():
    _write(_read() * 10)


SABOTAGE_FNS = {
    "SCHEMA_RENAME": _schema_rename,
    "TYPE_CORRUPTION": _type_corruption,
    "NULL_INJECTION": _null_injection,
    "EMPTY_DATA": _empty_data,
    "MISSING_FILE": _missing_file,
    "DATE_FORMAT": _date_format,
    "DUPLICATE_ROWS": _duplicate_rows,
}

_DESC = {
    "SCHEMA_RENAME": "rename temp->temperature, city->location in the source",
    "TYPE_CORRUPTION": "turn temp values into strings like '72.4F'",
    "NULL_INJECTION": "set temp=null on ~30% of records",
    "EMPTY_DATA": "replace the source with an empty list",
    "MISSING_FILE": "delete weather_source.json entirely",
    "DATE_FORMAT": "switch timestamps from ISO to MM/DD/YYYY HH:MM",
    "DUPLICATE_ROWS": "duplicate every record 10x",
}


def run_chaos(bus):
    """Pick + apply one sabotage. No-op if an incident is already active."""
    if bus.incident["active"]:
        return None
    recent = [i["chaos_sabotage"] for i in read_incident_log(5)]
    sabotage = decide_sabotage(recent)

    bus.emit(
        "chaos",
        "pipeline",
        "SABOTAGE_PLANNED",
        f"Planning sabotage: {sabotage} — {_DESC[sabotage]}",
        {"sabotage": sabotage},
    )
    SABOTAGE_FNS[sabotage]()
    bus.last_sabotage = sabotage
    bus.emit(
        "chaos",
        "monitor",
        "SABOTAGE_APPLIED",
        f"Applied {sabotage} to data/weather_source.json",
        {"sabotage": sabotage, "file": "data/weather_source.json"},
    )
    return sabotage
