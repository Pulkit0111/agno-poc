import pytest
from agno.db.sqlite import SqliteDb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bott.interfaces.console import sessions
from bott.interfaces.console.router import build_console_router


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "t3st")


@pytest.fixture()
def client(tmp_path):
    app = FastAPI()
    app.include_router(build_console_router(SqliteDb(db_file=str(tmp_path / "s.db"))))
    return TestClient(app)


def test_list_connectors(client, monkeypatch):
    fake = [{"name": "Slack", "ok": True, "on": "Connected", "off": "Add a token"}]
    import bott.interfaces.slack_home.connectors_panel as panel
    monkeypatch.setattr(panel, "connector_statuses", lambda: fake)
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session("m@x.com", False))
    r = client.get("/api/console/v1/connectors")
    assert r.status_code == 200
    assert r.json() == {"connectors": fake}


def test_requires_auth(client):
    assert client.get("/api/console/v1/connectors").status_code == 401
