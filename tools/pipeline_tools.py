import importlib
import json

from config import OUTPUT_FILE, PIPELINE_FILE
from restore import restore_data_only


def run_pipeline():
    """Reload pipeline.py from disk (picks up live patches) and run it."""
    import pipeline

    importlib.reload(pipeline)
    return pipeline.run()


def get_last_output():
    if not OUTPUT_FILE.exists():
        return None
    return json.loads(OUTPUT_FILE.read_text())


def restore_data_file():
    restore_data_only()
    return "weather_source.json restored from baseline"


def rewrite_pipeline_section(old_code, new_code):
    """Targeted str-replace edit of pipeline.py. Errors if `old_code` absent."""
    src = PIPELINE_FILE.read_text()
    if old_code not in src:
        raise ValueError("old_code not found in pipeline.py")
    PIPELINE_FILE.write_text(src.replace(old_code, new_code, 1))
    return "pipeline.py section rewritten"
