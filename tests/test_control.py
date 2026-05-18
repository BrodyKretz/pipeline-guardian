import os

import pytest
from fastapi.testclient import TestClient

os.environ["PG_DISABLE_SCHEDULER"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)

import main  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset():
    main.RUN_STATE = "running"
    main.llm.USE_REAL = False
    yield
    main.RUN_STATE = "running"
    main.llm.USE_REAL = False
    os.environ.pop("ANTHROPIC_API_KEY", None)


def test_state_includes_status(client):
    b = client.get("/api/state").json()
    assert b["run_state"] == "running"
    assert b["mode"] == "mock"
    assert b["has_key"] is False


def test_pause_makes_monitor_job_noop(client, monkeypatch):
    called = []
    monkeypatch.setattr(main.monitor_agent, "tick", lambda bus: called.append(1))

    client.post("/api/control/pause")
    assert main.RUN_STATE == "paused"
    main._monitor_job()
    assert called == []  # paused → no-op

    client.post("/api/control/start")
    main._monitor_job()
    assert called == [1]  # running → ran


def test_stop_clears_active_incident(client):
    main.bus.start_incident("EMPTY_DATA")
    assert main.bus.incident["active"] is True

    r = client.post("/api/control/stop")
    body = r.json()
    assert body["run_state"] == "stopped"
    assert main.bus.incident["active"] is False


def test_unknown_control_action_400(client):
    assert client.post("/api/control/frobnicate").status_code == 400


def test_mode_ai_without_key_requests_key(client):
    r = client.post("/api/mode", json={"mode": "ai"})
    body = r.json()
    assert body["needs_key"] is True
    assert main.llm.USE_REAL is False  # did NOT switch


def test_mode_ai_with_key_writes_env_and_switches(client, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr(main, "ENV_FILE", env)

    r = client.post("/api/mode", json={"mode": "ai", "key": "sk-ant-test123"})
    body = r.json()
    assert body["mode"] == "ai"
    assert main.llm.USE_REAL is True
    assert "ANTHROPIC_API_KEY=sk-ant-test123" in env.read_text()

    # switching back to mock flips the flag off
    r = client.post("/api/mode", json={"mode": "mock"})
    assert r.json()["mode"] == "mock"
    assert main.llm.USE_REAL is False


def test_write_env_key_preserves_other_lines(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DEMO_FAST=1\nANTHROPIC_API_KEY=old\nFOO=bar\n")
    monkeypatch.setattr(main, "ENV_FILE", env)

    main._write_env_key("new-key")

    txt = env.read_text()
    assert "ANTHROPIC_API_KEY=new-key" in txt
    assert "DEMO_FAST=1" in txt
    assert "FOO=bar" in txt
    assert "old" not in txt
