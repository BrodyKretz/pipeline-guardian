import json
from datetime import datetime

from config import DATA_FILE, OUTPUT_FILE


def run():
    """ETL: read weather_source.json, F->C + clean, write daily_summary.json.

    Never raises: all failures returned as a structured result dict so the
    monitor can read them cleanly.
    """
    rows_processed = 0
    try:
        if not DATA_FILE.exists():
            return {
                "success": False,
                "rows_processed": 0,
                "error": f"data file not found: {DATA_FILE}",
                "error_type": "FileNotFoundError",
            }
        raw = json.loads(DATA_FILE.read_text())
        if not isinstance(raw, list) or len(raw) == 0:
            return {
                "success": False,
                "rows_processed": 0,
                "error": "empty or non-list dataset",
                "error_type": "EmptyData",
            }
        out = []
        for rec in raw:
            temp_c = round((float(rec["temp"]) - 32) * 5.0 / 9.0, 2)
            city = rec["city"].strip()
            humidity = int(rec["humidity"])
            if not 0 <= humidity <= 100:
                raise ValueError(f"humidity out of range: {humidity}")
            ts = rec["timestamp"]
            datetime.fromisoformat(ts)
            out.append(
                {
                    "city": city,
                    "temp": temp_c,
                    "humidity": humidity,
                    "timestamp": ts,
                }
            )
            rows_processed += 1
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(out, indent=2))
        return {
            "success": True,
            "rows_processed": rows_processed,
            "error": None,
            "error_type": None,
        }
    except Exception as e:
        return {
            "success": False,
            "rows_processed": rows_processed,
            "error": str(e),
            "error_type": type(e).__name__,
        }
