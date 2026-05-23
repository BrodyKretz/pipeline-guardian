import pytest

from config import PIPELINE_FILE
from restore import restore_all
from tools.pipeline_tools import run_pipeline


@pytest.fixture(autouse=True)
def clean():
    restore_all()
    yield
    restore_all()


def test_run_pipeline_returns_success_on_baseline():
    r = run_pipeline()
    assert r["success"] is True
    assert r["rows_processed"] == 20


def test_run_pipeline_times_out_on_infinite_loop(monkeypatch):
    monkeypatch.setattr("config.PIPELINE_TIMEOUT_SEC", 2)
    PIPELINE_FILE.write_text("import time\n\ndef run():\n    time.sleep(60)\n")
    r = run_pipeline()
    assert r["success"] is False
    assert r["error_type"] == "Timeout"


def test_run_pipeline_surfaces_syntax_error_as_result():
    PIPELINE_FILE.write_text("def run(:\n    pass\n")  # invalid syntax
    r = run_pipeline()
    assert r["success"] is False
    assert r["rows_processed"] == 0
