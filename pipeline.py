import json
from datetime import datetime

from config import DATA_FILE, OUTPUT_FILE

_VALID_CONDITIONS = {
    "clear", "cloudy", "partly_cloudy", "rain", "storm", "snow", "fog",
}
_VALID_DIRS = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}


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
            station_id = rec["station_id"].strip()
            humidity = int(rec["humidity"])
            if not 0 <= humidity <= 100:
                raise ValueError(f"humidity out of range: {humidity}")
            conditions = rec["conditions"]
            if conditions not in _VALID_CONDITIONS:
                raise ValueError(f"unknown conditions: {conditions}")
            wind_speed = float(rec["wind_speed"])
            if wind_speed < 0:
                raise ValueError(f"negative wind_speed: {wind_speed}")
            wind_direction = rec["wind_direction"]
            if wind_direction not in _VALID_DIRS:
                raise ValueError(f"invalid wind_direction: {wind_direction}")
            pressure = float(rec["pressure"])
            if not 900 <= pressure <= 1100:
                raise ValueError(f"pressure out of range: {pressure}")
            precipitation = float(rec["precipitation"])
            if precipitation < 0:
                raise ValueError(f"negative precipitation: {precipitation}")
            ts = rec["timestamp"]
            datetime.fromisoformat(ts)
            out.append(
                {
                    "city": city,
                    "station_id": station_id,
                    "temp": temp_c,
                    "humidity": humidity,
                    "conditions": conditions,
                    "wind_speed": wind_speed,
                    "wind_direction": wind_direction,
                    "pressure": pressure,
                    "precipitation": precipitation,
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
