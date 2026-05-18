import os

import pytest
from fastapi.testclient import TestClient

os.environ["PG_DISABLE_SCHEDULER"] = "1"

from main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_root_serves_dashboard(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Pipeline Guard" in r.text


def test_api_state(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert "incident" in body and "events" in body
    assert any(e["type"] == "SYSTEM_STARTED" for e in body["events"])


def test_api_incidents(client):
    r = client.get("/api/incidents")
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body and "recent" in body
    assert isinstance(body["recent"], list)


def test_websocket_receives_events(client):
    with client.websocket_connect("/ws") as ws:
        bus_mod = __import__("main").bus
        bus_mod.emit("system", "system", "PING", "hello")
        msg = ws.receive_json()
        assert msg["type"] == "PING"
        assert msg["message"] == "hello"
