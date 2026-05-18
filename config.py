import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
MODEL = "claude-sonnet-4-6"
DEMO_FAST = os.getenv("DEMO_FAST", "0") == "1"

MONITOR_INTERVAL_SEC = 15 if DEMO_FAST else 60
CHAOS_MIN_SEC = 30 if DEMO_FAST else 180
CHAOS_MAX_SEC = 60 if DEMO_FAST else 360

DATA_FILE = ROOT / "data" / "weather_source.json"
OUTPUT_FILE = ROOT / "output" / "daily_summary.json"
PIPELINE_FILE = ROOT / "pipeline.py"
BASELINE_DIR = ROOT / "baseline"
INCIDENTS_DIR = ROOT / "incidents"
SUMMARY_FILE = INCIDENTS_DIR / "summary.json"
DB_FILE = INCIDENTS_DIR / "incidents.db"

CONF_DIRECT = 0.85
CONF_UNVERIFIED = 0.60

SABOTAGE_TYPES = [
    "SCHEMA_RENAME",
    "TYPE_CORRUPTION",
    "NULL_INJECTION",
    "EMPTY_DATA",
    "MISSING_FILE",
    "DATE_FORMAT",
    "DUPLICATE_ROWS",
]
AGENTS = [
    "chaos",
    "monitor",
    "diagnosis",
    "patch",
    "validator",
    "reporter",
    "pipeline",
    "system",
]
HEALTHY_ROW_COUNT = 20
