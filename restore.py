import shutil

from config import BASELINE_DIR, DATA_FILE, PIPELINE_FILE


def restore_data_only():
    """Restore weather_source.json to the pristine 20-record baseline."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(BASELINE_DIR / "weather_source.json", DATA_FILE)


def restore_all():
    """Restore BOTH working files from baseline. Called on startup and after
    every incident closes, so each incident is a clean, repeatable round."""
    restore_data_only()
    shutil.copy(BASELINE_DIR / "pipeline.py", PIPELINE_FILE)
