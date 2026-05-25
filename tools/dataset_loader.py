"""Parse arbitrary user-uploaded datasets into a list of dict records.

Accepts: JSON (array or envelope dict), JSONL, CSV. The endpoint that calls
this hands the raw bytes + the original filename; we sniff the format from
both. Number-like CSV cells get coerced to int/float.
"""

import csv
import json
from io import StringIO

# Common envelope keys to unwrap when the upload is a JSON dict whose payload
# is the records list. Covers REST conventions across most APIs.
_ENVELOPE_KEYS = ("data", "records", "results", "items", "rows", "payload")


def _extract_records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in _ENVELOPE_KEYS:
            if k in payload and isinstance(payload[k], list):
                return payload[k]
    raise ValueError(
        "could not find a records list at the top level "
        f"(expected an array, or a dict with one of {list(_ENVELOPE_KEYS)})"
    )


def _coerce_csv_cell(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _parse_csv(text):
    reader = csv.DictReader(StringIO(text))
    return [{k: _coerce_csv_cell(v) for k, v in row.items()} for row in reader]


def _parse_jsonl(text):
    records = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        records.append(json.loads(s))
    return records


def parse_dataset(raw_bytes, filename=""):
    """Return a list-of-dict records list from raw upload bytes + filename.

    Raises ValueError on anything that isn't a parseable JSON array, JSON
    envelope-with-array, JSONL, or CSV.
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    name = (filename or "").lower()

    if name.endswith(".csv"):
        return _parse_csv(text)
    if name.endswith(".jsonl") or name.endswith(".ndjson"):
        return _parse_jsonl(text)
    if name.endswith(".json"):
        return _extract_records(json.loads(text))

    # No extension or unfamiliar extension: sniff.
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            return _extract_records(json.loads(text))
        except json.JSONDecodeError:
            # Maybe JSONL
            return _parse_jsonl(text)
    # Fall back to CSV
    return _parse_csv(text)
