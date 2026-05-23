"""Reporter Agent — logs and summarizes every incident. Heals persist."""

import json
import uuid
from datetime import datetime, timezone

from config import INCIDENTS_DIR, SUMMARY_FILE
from tools.log_tools import write_incident_log


def _now():
    return datetime.now(timezone.utc).isoformat()


def _duration(started, ended):
    try:
        return int(
            (datetime.fromisoformat(ended) - datetime.fromisoformat(started))
            .total_seconds()
        )
    except (TypeError, ValueError):
        return 0


def _update_summary(failure_type, resolved):
    summary = {"resolved": {}, "escalated": {}}
    if SUMMARY_FILE.exists():
        try:
            summary = json.loads(SUMMARY_FILE.read_text())
        except json.JSONDecodeError:
            pass
    bucket = "resolved" if resolved else "escalated"
    summary.setdefault(bucket, {})
    key = failure_type or "UNKNOWN"
    summary[bucket][key] = summary[bucket].get(key, 0) + 1
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))


def run(bus, *, resolved, diag, fix):
    inc = bus.incident
    started = inc["start_time"]
    ended = _now()
    failure_type = diag.get("failure_type")
    record = {
        "incident_id": str(uuid.uuid4()),
        "started_at": started,
        "resolved_at": ended,
        "failure_type": failure_type,
        "chaos_sabotage": inc["sabotage_type"],
        "diagnosis_confidence": diag.get("confidence"),
        "fix_applied": fix,
        "resolved": bool(resolved),
        "duration_seconds": _duration(started, ended),
        "event_chain": list(inc["events"]),
    }

    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    (INCIDENTS_DIR / f"{ts}.json").write_text(json.dumps(record, indent=2))
    _update_summary(failure_type, resolved)
    write_incident_log(record)

    status = "resolved" if resolved else "escalated"
    bus.emit(
        "reporter",
        "system",
        "INCIDENT_CLOSED",
        f"Incident {status} in {record['duration_seconds']}s "
        f"({failure_type})",
        {"resolved": resolved, "duration": record["duration_seconds"]},
    )
    bus.close_incident()
    # Heals stick: do NOT restore files between incidents. The pipeline
    # genuinely hardens over time as patch's fixes accumulate. The STOP
    # button is the explicit reset; server startup also restores baseline.
    return record
