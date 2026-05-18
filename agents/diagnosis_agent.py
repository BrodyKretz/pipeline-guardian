"""Diagnosis Agent — classifies the root cause of a pipeline failure."""

from config import CONF_UNVERIFIED
from llm import diagnose


def run(bus, error):
    bus.emit("diagnosis", "monitor", "DIAGNOSIS_STARTED", "Analyzing failure")
    d = diagnose(error)
    if d["failure_type"] == "UNKNOWN" or d["confidence"] < CONF_UNVERIFIED:
        bus.emit(
            "diagnosis",
            "reporter",
            "ESCALATE",
            f"Low confidence ({d['confidence']:.2f}) / unknown — needs a human.",
            d,
        )
        return {**d, "escalated": True}
    bus.emit(
        "diagnosis",
        "patch",
        "DIAGNOSIS_COMPLETE",
        f"{d['failure_type']} ({d['confidence']:.2f}): {d['reasoning']}",
        d,
    )
    return d
