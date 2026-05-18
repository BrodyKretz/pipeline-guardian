import pytest

from restore import restore_all
from tools.file_tools import list_files, read_file, write_file
from tools.log_tools import read_incident_log, write_incident_log
from tools.pipeline_tools import (
    get_last_output,
    rewrite_pipeline_section,
    run_pipeline,
)


@pytest.fixture(autouse=True)
def clean():
    restore_all()
    yield
    restore_all()


def test_file_tools_roundtrip(tmp_path):
    write_file("output/_t.txt", "hello")
    assert read_file("output/_t.txt") == "hello"
    assert "output/_t.txt" in list_files("output")


def test_file_tools_reject_escape():
    with pytest.raises(ValueError):
        read_file("../../../etc/passwd")


def test_run_pipeline_returns_result_dict():
    r = run_pipeline()
    assert r["success"] is True and r["rows_processed"] == 20
    assert get_last_output() and len(get_last_output()) == 20


def test_rewrite_pipeline_section_errors_when_missing():
    with pytest.raises(ValueError):
        rewrite_pipeline_section("THIS_IS_NOT_IN_THE_FILE", "x")


def test_incident_log_roundtrip():
    rec = {
        "incident_id": "test-123",
        "started_at": "2026-05-17T00:00:00",
        "resolved_at": "2026-05-17T00:01:00",
        "failure_type": "EMPTY_DATA",
        "chaos_sabotage": "EMPTY_DATA",
        "diagnosis_confidence": 0.97,
        "fix_applied": "restored data",
        "resolved": True,
        "duration_seconds": 60,
        "event_chain": [{"type": "X"}],
    }
    write_incident_log(rec)
    rows = read_incident_log(5)
    assert any(r["incident_id"] == "test-123" for r in rows)
