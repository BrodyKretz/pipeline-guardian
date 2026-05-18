from db import init_db, insert_incident, recent_incidents


def write_incident_log(record):
    init_db()
    insert_incident(record)
    return f"incident {record['incident_id']} logged"


def read_incident_log(n=10):
    init_db()
    return recent_incidents(n)
