from config import BASELINE_DIR, DATA_FILE, PIPELINE_FILE
from restore import restore_all, restore_data_only


def test_restore_all_makes_working_files_match_baseline():
    DATA_FILE.write_text("[CORRUPTED]")
    PIPELINE_FILE.write_text("# sabotaged by chaos\n")

    restore_all()

    assert DATA_FILE.read_bytes() == (BASELINE_DIR / "weather_source.json").read_bytes()
    assert PIPELINE_FILE.read_bytes() == (BASELINE_DIR / "pipeline.py").read_bytes()


def test_restore_data_only_leaves_pipeline_untouched():
    PIPELINE_FILE.write_text("# patched\n")
    DATA_FILE.write_text("[]")

    restore_data_only()

    assert DATA_FILE.read_bytes() == (BASELINE_DIR / "weather_source.json").read_bytes()
    assert PIPELINE_FILE.read_text() == "# patched\n"
    # cleanup so other tests get a clean pipeline
    restore_all()
