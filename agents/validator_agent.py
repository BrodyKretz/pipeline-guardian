"""Validator Agent — re-runs the pipeline and confirms the fix worked."""

import llm
from config import HEALTHY_ROW_COUNT
from tools.pipeline_tools import get_last_output, run_pipeline

_EXPECTED_KEYS = {
    "city", "station_id", "temp", "humidity", "conditions",
    "wind_speed", "wind_direction", "pressure", "precipitation", "timestamp",
}


def _schema_ok():
    out = get_last_output()
    if not out or not isinstance(out, list):
        return False
    row = out[0]
    return (
        set(row) == _EXPECTED_KEYS
        and isinstance(row["temp"], float)
        and isinstance(row["humidity"], int)
        and isinstance(row["city"], str)
        and isinstance(row["pressure"], float)
        and isinstance(row["wind_speed"], float)
    )


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
    r = run_pipeline()
    ok = (
        r["success"]
        and 1 <= r["rows_processed"] <= HEALTHY_ROW_COUNT
        and _schema_ok()
    )
    if ok:
        bus.emit(
            "validator",
            "reporter",
            "VALIDATION_PASSED",
            f"{r['rows_processed']} rows, schema OK",
            {"rows": r["rows_processed"]},
        )
        return True
    bus.emit(
        "validator",
        "reporter",
        "VALIDATION_FAILED",
        f"Still broken: success={r['success']} rows={r['rows_processed']} "
        f"error={r['error']}",
        {"result": r},
    )
    bus.emit(
        "validator", "system", "ESCALATE", "Fix did not resolve the issue."
    )
    return False
