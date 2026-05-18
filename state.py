import threading
import uuid
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


class EventBus:
    """Central nervous system: append-only event log + incident state +
    WebSocket broadcast bridge from scheduler threads to the asyncio loop."""

    def __init__(self):
        self.events = []
        self.connections = set()
        self.lock = threading.Lock()
        self._loop = None
        self._queue = None
        self.last_sabotage = None
        self.incident = self._empty_incident()

    @staticmethod
    def _empty_incident():
        return {
            "active": False,
            "failure_type": None,
            "sabotage_type": None,
            "start_time": None,
            "events": [],
        }

    def register_loop(self, loop, queue):
        """Called from the FastAPI startup so emit() can cross thread->async."""
        self._loop = loop
        self._queue = queue

    def emit(self, from_agent, to_agent, type, message, data=None):
        event = {
            "id": str(uuid.uuid4()),
            "timestamp": _now(),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "type": type,
            "message": message,
            "data": data or {},
        }
        self.events.append(event)
        if self.incident["active"]:
            self.incident["events"].append(event)
        if self._loop is not None and self._queue is not None:
            try:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
            except RuntimeError:
                pass
        return event

    def start_incident(self, sabotage_type=None):
        self.incident = self._empty_incident()
        self.incident["active"] = True
        self.incident["start_time"] = _now()
        self.incident["sabotage_type"] = sabotage_type

    def set_sabotage(self, sabotage_type):
        self.incident["sabotage_type"] = sabotage_type

    def close_incident(self):
        self.incident["active"] = False

    def reset(self):
        """Wipe runtime state to a clean slate. Keeps WS connections and the
        loop/queue binding so the dashboard stays connected."""
        self.events = []
        self.incident = self._empty_incident()
        self.last_sabotage = None

    def recent_events(self, n=50):
        return self.events[-n:]
