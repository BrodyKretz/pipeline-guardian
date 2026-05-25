import json

import pytest

from tools.dataset_loader import parse_dataset


def test_parses_plain_json_array():
    raw = b'[{"a": 1}, {"a": 2}]'
    recs = parse_dataset(raw, "x.json")
    assert recs == [{"a": 1}, {"a": 2}]


def test_unwraps_envelope_with_data_key():
    raw = json.dumps({"meta": {"v": 2}, "data": [{"a": 1}, {"a": 2}]}).encode()
    recs = parse_dataset(raw, "x.json")
    assert recs == [{"a": 1}, {"a": 2}]


def test_unwraps_envelope_with_records_key():
    raw = json.dumps({"records": [{"x": 1}]}).encode()
    recs = parse_dataset(raw, "x.json")
    assert recs == [{"x": 1}]


def test_parses_jsonl():
    raw = b'{"a":1}\n{"a":2}\n{"a":3}\n'
    recs = parse_dataset(raw, "x.jsonl")
    assert recs == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_parses_csv_with_numeric_coercion():
    raw = b"city,temp,humidity\nBoulder,45.3,29\nDenver,65.5,74\n"
    recs = parse_dataset(raw, "x.csv")
    assert recs == [
        {"city": "Boulder", "temp": 45.3, "humidity": 29},
        {"city": "Denver", "temp": 65.5, "humidity": 74},
    ]


def test_csv_blank_cell_becomes_none():
    raw = b"a,b\n1,\n2,foo\n"
    recs = parse_dataset(raw, "x.csv")
    assert recs == [{"a": 1, "b": None}, {"a": 2, "b": "foo"}]


def test_sniffs_format_without_extension():
    json_raw = b'[{"a": 1}]'
    assert parse_dataset(json_raw, "") == [{"a": 1}]
    csv_raw = b"a,b\n1,2\n"
    assert parse_dataset(csv_raw, "") == [{"a": 1, "b": 2}]


def test_rejects_non_array_payload():
    raw = b'{"single": "object"}'
    with pytest.raises(ValueError):
        parse_dataset(raw, "x.json")
