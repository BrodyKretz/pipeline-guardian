"""Chaos Agent — deliberately sabotages the pipeline's data source."""

import json

import llm
from config import DATA_FILE, PIPELINE_FILE, WRITABLE_FILES
from llm import decide_sabotage
from tools.file_events import emit_file_change, track_changes
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


def _ai_chaos(bus):
    """Creative branch: the model invents and writes one breaking change.

    Hard guards enforce the "realistic upstream failures only" constraint:
    no pipeline.py edits (that's a bad deploy, not an upstream issue), no
    emptying the data feed (that's infra failure, not data drift)."""

    def write_fn(path_str, content):
        target = next(
            (p for p in WRITABLE_FILES if str(p).endswith(path_str)), None
        )
        if target is None:
            return f"refused: {path_str} is not writable"
        if target == PIPELINE_FILE:
            return (
                "error: chaos may only mutate the upstream data feed, not the "
                "pipeline code. Edit data/weather_source.json instead."
            )
        if not content or not content.strip():
            return "error: chaos may not empty the data feed."
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list) and len(parsed) == 0:
                return (
                    "error: chaos may not empty the dataset. Mutate records "
                    "(rename, drift, corrupt values) instead."
                )
        except json.JSONDecodeError:
            pass  # non-JSON content is allowed (realistic corrupted feed)
        before = target.read_text() if target.exists() else None
        target.write_text(content)
        emit_file_change(bus, "chaos", "damage", target, before, content)
        return f"wrote {len(content)} chars to {path_str}"

    bus.emit("chaos", "pipeline", "SABOTAGE_PLANNED", "Planning a creative sabotage")
    result = llm.generate_sabotage(write_fn)
    if not result["applied"]:
        # Model planned but never produced a valid write (guards refused, or it
        # gave up). Be honest: no SABOTAGE_APPLIED, monitor will see healthy.
        bus.emit(
            "chaos",
            "system",
            "SABOTAGE_ABORTED",
            "Chaos planned a change but no valid mutation was applied "
            "(guards refused or model gave up).",
        )
        return None
    note = result["note"]
    bus.last_sabotage = note or "creative"
    bus.emit(
        "chaos",
        "monitor",
        "SABOTAGE_APPLIED",
        f"Chaos applied a change ({note})",
        {"note": note},
    )
    return note


def run_chaos(bus):
    """Pick + apply one sabotage. No-op if an incident is already active."""
    if bus.incident["active"]:
        return None
    if llm.USE_REAL:
        return _ai_chaos(bus)

    recent = [i["chaos_sabotage"] for i in read_incident_log(5)]
    sabotage = decide_sabotage(recent)

    bus.emit(
        "chaos",
        "pipeline",
        "SABOTAGE_PLANNED",
        f"Planning sabotage: {sabotage} — {_DESC[sabotage]}",
        {"sabotage": sabotage},
    )
    with track_changes(bus, "chaos", "damage", [DATA_FILE, PIPELINE_FILE]):
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
