import json
import sqlite3

from config import DB_FILE


def _conn():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_FILE)


def init_db():
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id   TEXT PRIMARY KEY,
                started_at    TEXT,
                resolved_at   TEXT,
                failure_type  TEXT,
                chaos_sabotage TEXT,
                diagnosis_confidence REAL,
                fix_applied   TEXT,
                resolved      INTEGER,
                duration_seconds INTEGER,
                event_chain   TEXT
            )
            """
        )


def insert_incident(record):
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO incidents VALUES
               (:incident_id,:started_at,:resolved_at,:failure_type,
                :chaos_sabotage,:diagnosis_confidence,:fix_applied,
                :resolved,:duration_seconds,:event_chain)""",
            {
                **record,
                "resolved": int(record["resolved"]),
                "event_chain": json.dumps(record["event_chain"]),
            },
        )


def recent_incidents(n=10):
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT incident_id,started_at,resolved_at,failure_type,"
            "chaos_sabotage,diagnosis_confidence,fix_applied,resolved,"
            "duration_seconds FROM incidents ORDER BY started_at DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [dict(r) for r in rows]
