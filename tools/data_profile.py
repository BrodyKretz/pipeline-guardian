"""Derive and apply a compliance profile from a dataset.

The profile is the contract: it captures the shape, types, ranges, and enums
of a 'known-good' dataset at ingest time. Once it exists, it is the source of
truth for 'what correct looks like.' Chaos drifts from it; patch heals back
toward it; validator checks compliance against it.

Unlike the baseline files, the profile is AI-visible — agents reason against
it in their prompts. The baseline still exists for the explicit STOP / restart
reset, and stays harness-only.
"""

import json
from datetime import datetime
from pathlib import Path


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
            pass
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


# A field is considered an enum if its observed unique string values fit
# under this cap. Above it, we treat the field as free-form text.
_ENUM_CAP = 20


def derive_profile(records):
    """Profile a list of dict records.

    Returns:
        {
          "row_count": int,
          "fields": {
            <field_name>: {
              "type": <inferred type>,
              "nullable": bool,
              "min": <numeric only>, "max": <numeric only>,
              "enum": [<sorted unique strings>] if small enough,
              "examples": [<up to 3>]
            },
            ...
          }
        }
    """
    if not isinstance(records, list) or not records:
        return {"row_count": 0, "fields": {}}

    fields = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        for k, v in rec.items():
            f = fields.setdefault(
                k,
                {
                    "type": None,
                    "nullable": False,
                    "examples": [],
                    "min": None,
                    "max": None,
                    "_enum_candidates": set(),
                },
            )
            if v is None:
                f["nullable"] = True
                continue
            t = _infer_type(v)
            if f["type"] is None:
                f["type"] = t
            elif f["type"] != t:
                # tolerate int↔number, but degrade anything else to 'mixed'
                if {f["type"], t} <= {"integer", "number"}:
                    f["type"] = "number"
                else:
                    f["type"] = "mixed"
            if t in ("integer", "number"):
                if f["min"] is None or v < f["min"]:
                    f["min"] = v
                if f["max"] is None or v > f["max"]:
                    f["max"] = v
            if t == "string":
                f["_enum_candidates"].add(v)
            if len(f["examples"]) < 3:
                f["examples"].append(v)

    for k, f in fields.items():
        cands = f.pop("_enum_candidates", set())
        if f["type"] == "string" and 0 < len(cands) <= _ENUM_CAP:
            f["enum"] = sorted(cands)

    return {"row_count": len(records), "fields": fields}


def check_compliance(records, profile):
    """Validate records against a profile. Returns (ok, [issues]).

    ok is True when there are zero structural/type/range/enum issues.
    Each issue is a one-line human-readable string with row index + field.
    """
    issues = []
    if not isinstance(records, list):
        return False, ["payload is not a list"]
    spec_fields = profile.get("fields", {})
    expected = set(spec_fields.keys())

    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            issues.append(f"row {i}: not a dict")
            continue
        keys = set(rec.keys())
        missing = expected - keys
        extra = keys - expected
        if missing:
            issues.append(f"row {i}: missing {sorted(missing)}")
        if extra:
            issues.append(f"row {i}: unexpected {sorted(extra)}")

        for field, spec in spec_fields.items():
            if field not in rec:
                continue
            v = rec[field]
            if v is None:
                if not spec.get("nullable"):
                    issues.append(
                        f"row {i}: {field} is null but profile is non-null"
                    )
                continue
            actual = _infer_type(v)
            expected_type = spec.get("type")
            if expected_type and expected_type != "mixed":
                ok = actual == expected_type
                # tolerate int where number is expected (and vice versa)
                if not ok and {actual, expected_type} <= {"integer", "number"}:
                    ok = True
                if not ok:
                    issues.append(
                        f"row {i}: {field} type {actual}, expected {expected_type}"
                    )
            if expected_type in ("integer", "number") and isinstance(v, (int, float)):
                lo, hi = spec.get("min"), spec.get("max")
                if lo is not None and v < lo:
                    issues.append(f"row {i}: {field}={v} below min {lo}")
                if hi is not None and v > hi:
                    issues.append(f"row {i}: {field}={v} above max {hi}")
            enum = spec.get("enum")
            if enum and v not in enum:
                issues.append(
                    f"row {i}: {field}={v!r} not in enum {enum[:5]}..."
                )

    return len(issues) == 0, issues


def load_or_derive(profile_path, source_records_path):
    """Load profile from disk if present; otherwise derive it from the
    source records file and write it next to that file."""
    p = Path(profile_path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    src = Path(source_records_path)
    if not src.exists():
        return {"row_count": 0, "fields": {}}
    records = json.loads(src.read_text())
    profile = derive_profile(records)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile, indent=2))
    return profile
