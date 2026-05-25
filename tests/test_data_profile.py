import json

from tools.data_profile import check_compliance, derive_profile


def test_derive_basic_shape():
    p = derive_profile(
        [
            {"city": "Boulder", "temp": 45.3, "humidity": 29},
            {"city": "Denver", "temp": 65.5, "humidity": 74},
        ]
    )
    assert p["row_count"] == 2
    assert p["fields"]["city"]["type"] == "string"
    assert p["fields"]["temp"]["type"] == "number"
    assert p["fields"]["humidity"]["type"] == "integer"
    assert p["fields"]["temp"]["min"] == 45.3
    assert p["fields"]["temp"]["max"] == 65.5


def test_derive_detects_enum_when_few_uniques():
    p = derive_profile(
        [{"dir": d} for d in ["N", "S", "N", "E", "W", "N"]]
    )
    assert set(p["fields"]["dir"]["enum"]) == {"N", "S", "E", "W"}


def test_derive_skips_enum_when_too_many_uniques():
    p = derive_profile([{"name": f"city_{i}"} for i in range(50)])
    assert "enum" not in p["fields"]["name"]


def test_derive_detects_nullability():
    p = derive_profile(
        [{"temp": 45.3}, {"temp": None}, {"temp": 50.1}]
    )
    assert p["fields"]["temp"]["nullable"] is True


def test_derive_detects_iso8601_string():
    p = derive_profile([{"t": "2026-05-17T08:00:00"}])
    assert p["fields"]["t"]["type"] == "iso8601"


def test_check_compliance_passes_on_clean_data():
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    p = derive_profile(rows)
    ok, issues = check_compliance(rows, p)
    assert ok and issues == []


def test_check_compliance_flags_missing_field():
    rows = [{"a": 1, "b": "x"}]
    p = derive_profile(rows)
    ok, issues = check_compliance([{"a": 1}], p)
    assert not ok
    assert any("missing" in i for i in issues)


def test_check_compliance_flags_out_of_range():
    rows = [{"h": 30}, {"h": 70}]  # min=30, max=70
    p = derive_profile(rows)
    ok, issues = check_compliance([{"h": 200}], p)
    assert not ok
    assert any("above max" in i for i in issues)


def test_check_compliance_flags_enum_violation():
    rows = [{"c": "clear"}, {"c": "rain"}]
    p = derive_profile(rows)
    ok, issues = check_compliance([{"c": "tornado"}], p)
    assert not ok
    assert any("not in enum" in i for i in issues)


def test_load_or_derive_writes_profile(tmp_path):
    from tools.data_profile import load_or_derive

    src = tmp_path / "src.json"
    src.write_text(json.dumps([{"x": 1}, {"x": 2}]))
    prof_path = tmp_path / "profile.json"
    p = load_or_derive(prof_path, src)
    assert p["row_count"] == 2
    assert prof_path.exists()
    # second call reads from disk, doesn't re-derive
    src.write_text("garbage not json")  # would crash if re-derived
    p2 = load_or_derive(prof_path, src)
    assert p2 == p
