from state import EventBus


def test_emit_appends_and_tracks_incident():
    bus = EventBus()
    bus.start_incident("EMPTY_DATA")
    bus.emit("monitor", "diagnosis", "FAILURE_DETECTED", "boom", {"x": 1})
    assert len(bus.events) == 1
    e = bus.events[0]
    assert e["from_agent"] == "monitor" and e["to_agent"] == "diagnosis"
    assert e["type"] == "FAILURE_DETECTED" and e["data"] == {"x": 1}
    assert e["id"] and e["timestamp"]
    assert bus.incident["active"] is True
    assert bus.incident["sabotage_type"] == "EMPTY_DATA"
    assert len(bus.incident["events"]) == 1


def test_emit_without_loop_does_not_raise():
    bus = EventBus()
    bus.emit("system", "system", "SYSTEM_STARTED", "up")
    assert len(bus.events) == 1
    assert bus.incident["events"] == []  # no active incident


def test_close_incident():
    bus = EventBus()
    bus.start_incident()
    bus.close_incident()
    assert bus.incident["active"] is False
