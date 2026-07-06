import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agno.db.sqlite import SqliteDb

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


def _as(client, email="m@x.com", admin=True):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, admin))


def test_status_requires_admin(client):
    _as(client, admin=False)
    assert client.get("/api/console/v1/system").status_code == 403


def test_status_shape(client, monkeypatch):
    import bott.interfaces.slack_home.models as models_mod
    monkeypatch.setattr(models_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-5.5", "build": "gpt-5.5-codex", "review": "gpt-5.5",
    })
    _as(client)
    body = client.get("/api/console/v1/system").json()
    assert "model" in body and "database" in body and "connectors" in body and "advisories" in body


def test_unconfigured_connector_becomes_advisory(client, monkeypatch):
    from bott.shared import config
    monkeypatch.setattr(config, "sentry_configured", lambda: False)
    _as(client)
    body = client.get("/api/console/v1/system").json()
    assert any(a["name"] == "sentry" for a in body["advisories"])


def test_review_trends_requires_admin(client):
    _as(client, admin=False)
    assert client.get("/api/console/v1/system/review-trends").status_code == 403


def test_review_trends(client, monkeypatch):
    from bott.shared.persistence import records
    monkeypatch.setattr(records, "trace_stats_by_week", lambda since_epoch=None: {"2026-W27": {"approve": 3}})
    _as(client)
    body = client.get("/api/console/v1/system/review-trends").json()
    assert body == {"by_week": {"2026-W27": {"approve": 3}}}
