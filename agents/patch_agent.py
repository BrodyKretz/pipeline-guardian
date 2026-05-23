"""Patch Agent — applies the targeted fix for a confirmed failure type.

Patches always operate on the pristine baseline pipeline.py (restored after
every incident), so the string-replacement targets are deterministic.
"""

import llm
from config import CONF_DIRECT, CONF_UNVERIFIED, DATA_FILE, PIPELINE_FILE, WRITABLE_FILES
from restore import restore_data_only
from tools.file_events import emit_file_change, track_changes


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


def _ai_patch(bus, diag, feedback=None):
    """Generative branch: the model reads the files and writes the fix itself.

    Hard guards enforce the "no fabrication" rule on the data file:
    patch can shrink, clean, clamp, dedupe — but never grow record count
    or rewrite data from scratch when the source is unparseable. Forces
    the model to edit pipeline.py or escalate in those cases."""

    import json as _json

    def write_fn(path_str, content):
        target = next(
            (p for p in WRITABLE_FILES if str(p).endswith(path_str)), None
        )
        if target is None:
            return f"refused: {path_str} not writable"
        if target == DATA_FILE:
            current = target.read_text() if target.exists() else ""
            try:
                cur = _json.loads(current)
            except _json.JSONDecodeError:
                return (
                    "error: current data is unparseable. Do NOT rewrite the "
                    "data file — edit pipeline.py to handle the new shape, "
                    "or submit_patch with a low-confidence note to escalate."
                )
            try:
                new = _json.loads(content)
            except _json.JSONDecodeError:
                return "error: proposed data content is not valid JSON."
            if isinstance(cur, list) and isinstance(new, list):
                if len(new) > len(cur):
                    return (
                        f"error: patch may not add records that weren't in "
                        f"the source ({len(cur)} -> {len(new)}). Filtering, "
                        f"cleaning, clamping is allowed; inventing rows is "
                        f"not. Edit pipeline.py instead, or escalate."
                    )
            elif not isinstance(cur, list):
                return (
                    "error: current data is not a JSON list. Do not rewrite "
                    "data — edit pipeline.py to handle the new shape."
                )
        before = target.read_text() if target.exists() else None
        target.write_text(content)
        emit_file_change(bus, "patch", "heal", target, before, content)
        return f"wrote {len(content)} chars to {path_str}"

    out = llm.generate_patch(diag, write_fn, feedback)
    summary = out.get("summary", "patch applied")
    bus.emit("patch", "validator", "PATCH_APPLIED", summary, {"fix": summary})
    return {"fix": summary}


def run(bus, diag, feedback=None):
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

    if llm.USE_REAL:
        return _ai_patch(bus, diag, feedback)

    with track_changes(bus, "patch", "heal", [DATA_FILE, PIPELINE_FILE]):
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
