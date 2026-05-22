"""Monitor Agent — periodically runs the pipeline and drives the healing
chain synchronously when a failure (or row-count anomaly) is detected."""

import llm
from config import HEALTHY_ROW_COUNT
from tools.pipeline_tools import run_pipeline

from agents import diagnosis_agent, patch_agent, reporter_agent, validator_agent


def _run_chain(bus, error):
    diag = diagnosis_agent.run(bus, error)
    if diag.get("escalated"):
        reporter_agent.run(
            bus, resolved=False, diag=diag, fix="none — escalated at diagnosis"
        )
        return
    patch_res = patch_agent.run(bus, diag)
    if patch_res.get("escalated"):
        reporter_agent.run(
            bus, resolved=False, diag=diag, fix="none — escalated at patch"
        )
        return
    passed = validator_agent.run(bus)
    if not passed and llm.USE_REAL:
        patch_res = patch_agent.run(
            bus, diag, feedback="previous fix failed validation"
        )
        passed = validator_agent.run(bus)
    reporter_agent.run(bus, resolved=passed, diag=diag, fix=patch_res["fix"])


def tick(bus):
    """One monitor cycle. Returns the raw pipeline result."""
    bus.emit("monitor", "pipeline", "PIPELINE_TRIGGERED", "Running pipeline check")
    result = run_pipeline()
    healthy = (
        result["success"]
        and 1 <= result["rows_processed"] <= HEALTHY_ROW_COUNT
    )
    if healthy:
        bus.emit(
            "monitor",
            "system",
            "PIPELINE_HEALTHY",
            f"Pipeline OK — {result['rows_processed']} rows processed",
            {"rows": result["rows_processed"]},
        )
        return result

    if bus.incident["active"]:
        return result  # chain already running for this incident

    with bus.lock:
        bus.start_incident(bus.last_sabotage)
        error = result["error"] or (
            f"row-count anomaly: {result['rows_processed']} rows "
            f"(expected <= {HEALTHY_ROW_COUNT})"
        )
        bus.emit(
            "monitor",
            "diagnosis",
            "FAILURE_DETECTED",
            error,
            {"result": result},
        )
        _run_chain(bus, error)
    return result
