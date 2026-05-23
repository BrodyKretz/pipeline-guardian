import pytest

from config import DATA_FILE, PIPELINE_FILE, ROOT
from restore import restore_all
from state import EventBus
from tools.file_events import emit_file_change, track_changes


@pytest.fixture(autouse=True)
def clean():
    restore_all()
    yield
    restore_all()


def test_emit_file_change_publishes_event_with_attribution():
    bus = EventBus()
    emit_file_change(bus, "chaos", "damage", DATA_FILE, "before", "after")
    ev = bus.events[-1]
    assert ev["type"] == "FILE_CHANGED"
    assert ev["from_agent"] == "chaos"
    assert ev["data"]["kind"] == "damage"
    assert ev["data"]["before"] == "before"
    assert ev["data"]["after"] == "after"
    assert ev["data"]["path"] == "data/weather_source.json"


def test_track_changes_emits_only_for_files_that_changed():
    bus = EventBus()
    with track_changes(bus, "patch", "heal", [DATA_FILE, PIPELINE_FILE]):
        DATA_FILE.write_text("mutated")
    changed = [e for e in bus.events if e["type"] == "FILE_CHANGED"]
    assert len(changed) == 1
    assert changed[0]["data"]["path"] == "data/weather_source.json"
    assert changed[0]["data"]["after"] == "mutated"


def test_track_changes_rejects_non_whitelisted_path():
    bus = EventBus()
    outside = ROOT / "llm.py"
    with pytest.raises(ValueError):
        with track_changes(bus, "chaos", "damage", [outside]):
            pass
