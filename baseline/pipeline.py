"""Generic profile-driven ETL.

The pipeline is now dataset-agnostic. It reads the compliance profile from
data/compliance.json and validates every input record against it (types,
nullability, numeric ranges, string enums, ISO timestamps). Whatever
dataset is loaded — weather, songs, transactions, anything — flows
through the same code. No transforms; validation only.

Never raises: all failures returned as a structured result dict so the
monitor can read them cleanly.
"""

import json
from datetime import datetime

from config import DATA_FILE, OUTPUT_FILE, ROOT

_PROFILE_FILE = ROOT / "data" / "compliance.json"


def _infer_type(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value)
            return "iso8601"
        except ValueError:
            return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _types_compat(actual, expected):
    if actual == expected:
        return True
    if {actual, expected} <= {"integer", "number"}:
        return True
    # accept any string where iso8601 was expected if it parses
    return False


def _validate_record(rec, fields):
    expected_keys = set(fields)
    keys = set(rec.keys())
    missing = expected_keys - keys
    if missing:
        raise KeyError(f"missing fields: {sorted(missing)}")
    extra = keys - expected_keys
    if extra:
        raise ValueError(f"unexpected fields: {sorted(extra)}")
    for field, spec in fields.items():
        v = rec[field]
        if v is None:
            if not spec.get("nullable"):
                raise ValueError(f"{field} is null but profile is non-null")
            continue
        expected_type = spec.get("type")
        if expected_type and expected_type != "mixed":
            actual = _infer_type(v)
            if not _types_compat(actual, expected_type):
                raise TypeError(
                    f"{field} expected {expected_type}, got {actual}"
                )
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            lo, hi = spec.get("min"), spec.get("max")
            if lo is not None and v < lo:
                raise ValueError(f"{field}={v} below min {lo}")
            if hi is not None and v > hi:
                raise ValueError(f"{field}={v} above max {hi}")
        enum = spec.get("enum")
        if enum and v not in enum:
            raise ValueError(f"{field}={v!r} not in enum")


def run():
    rows_processed = 0
    try:
        if not DATA_FILE.exists():
            return {
                "success": False,
                "rows_processed": 0,
                "error": f"data file not found: {DATA_FILE}",
                "error_type": "FileNotFoundError",
            }
        raw = json.loads(DATA_FILE.read_text())
        if not isinstance(raw, list) or len(raw) == 0:
            return {
                "success": False,
                "rows_processed": 0,
                "error": "empty or non-list dataset",
                "error_type": "EmptyData",
            }
        if not _PROFILE_FILE.exists():
            return {
                "success": False,
                "rows_processed": 0,
                "error": "compliance profile missing; cannot validate",
                "error_type": "MissingProfile",
            }
        profile = json.loads(_PROFILE_FILE.read_text())
        fields = profile.get("fields", {})

        out = []
        for rec in raw:
            if not isinstance(rec, dict):
                raise TypeError(f"row {rows_processed}: not a dict")
            _validate_record(rec, fields)
            out.append(rec)
            rows_processed += 1
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(out, indent=2))
        return {
            "success": True,
            "rows_processed": rows_processed,
            "error": None,
            "error_type": None,
        }
    except Exception as e:
        return {
            "success": False,
            "rows_processed": rows_processed,
            "error": str(e),
            "error_type": type(e).__name__,
        }
