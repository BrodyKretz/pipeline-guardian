"""Patch Agent — applies the targeted fix for a confirmed failure type.

Patches always operate on the pristine baseline pipeline.py (restored after
every incident), so the string-replacement targets are deterministic.
"""

from config import CONF_DIRECT, CONF_UNVERIFIED, PIPELINE_FILE
from restore import restore_data_only


def restore_data_file():
    restore_data_only()


def rewrite_pipeline_section(old_code, new_code):
    src = PIPELINE_FILE.read_text()
    if old_code not in src:
        raise ValueError("old_code not found in pipeline.py")
    PIPELINE_FILE.write_text(src.replace(old_code, new_code, 1))

_SCHEMA_OLD = (
    'temp_c = round((float(rec["temp"]) - 32) * 5.0 / 9.0, 2)\n'
    '            city = rec["city"].strip()'
)
_SCHEMA_NEW = (
    'temp_c = round((float(rec.get("temp", rec.get("temperature"))) - 32)'
    " * 5.0 / 9.0, 2)\n"
    '            city = (rec.get("city") or rec.get("location")).strip()'
)


def _apply_fix(failure_type):
    if failure_type in ("EMPTY_DATA", "MISSING_FILE"):
        restore_data_file()
        return "Restored weather_source.json from baseline."
    if failure_type == "SCHEMA_RENAME":
        rewrite_pipeline_section(_SCHEMA_OLD, _SCHEMA_NEW)
        return "Pipeline reads renamed keys (temperature/location) with fallback."
    if failure_type == "TYPE_CORRUPTION":
        rewrite_pipeline_section(
            'float(rec["temp"])',
            'float(str(rec["temp"]).rstrip("Ff").strip())',
        )
        return "Added numeric coercion for string-typed temps."
    if failure_type == "NULL_INJECTION":
        rewrite_pipeline_section(
            "for rec in raw:",
            "for rec in [r for r in raw if r.get(\"temp\") is not None]:",
        )
        return "Filter out null-temp records before transform."
    if failure_type == "DATE_FORMAT":
        rewrite_pipeline_section(
            "datetime.fromisoformat(ts)",
            '(datetime.fromisoformat(ts) if "T" in ts '
            'else datetime.strptime(ts, "%m/%d/%Y %H:%M"))',
        )
        return "Added flexible timestamp parsing (ISO + MM/DD/YYYY HH:MM)."
    if failure_type == "DUPLICATE_ROWS":
        rewrite_pipeline_section(
            "raw = json.loads(DATA_FILE.read_text())",
            "raw = json.loads(DATA_FILE.read_text())\n"
            "        if isinstance(raw, list):\n"
            "            raw = [json.loads(s) for s in dict.fromkeys("
            "json.dumps(r, sort_keys=True) for r in raw)]",
        )
        return "Added deduplication step before transform."
    raise ValueError(f"no patch strategy for {failure_type}")


def run(bus, diag):
    ft = diag["failure_type"]
    conf = diag["confidence"]
    bus.emit(
        "patch",
        "diagnosis",
        "PATCH_STARTED",
        f"Planning fix for {ft} (confidence {conf:.2f})",
        {"failure_type": ft, "confidence": conf},
    )
    if conf < CONF_UNVERIFIED:
        bus.emit(
            "patch",
            "reporter",
            "ESCALATE",
            f"Confidence {conf:.2f} below patch threshold; not touching code.",
            diag,
        )
        return {"escalated": True}

    fix_desc = _apply_fix(ft)
    unverified = conf < CONF_DIRECT
    label = fix_desc + (" [UNVERIFIED]" if unverified else "")
    bus.emit(
        "patch",
        "validator",
        "PATCH_APPLIED",
        label,
        {"fix": fix_desc, "unverified": unverified},
    )
    return {"fix": fix_desc, "unverified": unverified}
