import pytest
from agno.db.sqlite import SqliteDb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bott.interfaces.console import sessions
from bott.interfaces.console.router import build_console_router


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "t3st")
    monkeypatch.setenv("BOTT_ADMINS", "admin@x.com")


@pytest.fixture()
def client(tmp_path):
    app = FastAPI()
    app.include_router(build_console_router(SqliteDb(db_file=str(tmp_path / "s.db"))))
    return TestClient(app)


def _as(client, email="m@x.com", admin=True):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, admin))


def test_requires_admin(client):
    _as(client, admin=False)
    assert client.post("/api/console/v1/connectors/jira/test").status_code == 403


def test_requires_auth(client):
    assert client.post("/api/console/v1/connectors/jira/test").status_code == 401


def test_unknown_connector_404s(client):
    _as(client, email="admin@x.com")
    r = client.post("/api/console/v1/connectors/not-a-thing/test")
    assert r.status_code == 404
    assert r.json()["detail"]["error"]["code"] == "unknown_connector"


def test_passes_through_probe_result(client, monkeypatch):
    from bott.skills.connectors import probes

    calls = []

    def fake_probe(name, subject_email=None):
        calls.append((name, subject_email))
        return {"ok": True, "message": "Connected to Jira as Bott Bot."}

    monkeypatch.setattr(probes, "probe", fake_probe)
    _as(client, email="admin@x.com")
    r = client.post("/api/console/v1/connectors/jira/test")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message": "Connected to Jira as Bott Bot."}
    assert calls == [("jira", "admin@x.com")]


def test_passes_through_failure_shape(client, monkeypatch):
    from bott.skills.connectors import probes

    monkeypatch.setattr(probes, "probe", lambda name, subject_email=None: {
        "ok": False, "message": "Couldn't reach sentry (401 Unauthorized).",
    })
    _as(client, email="admin@x.com")
    r = client.post("/api/console/v1/connectors/sentry/test")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "Couldn't reach sentry (401 Unauthorized)."}


def test_uses_signed_in_admin_email_for_delegated_probes(client, monkeypatch):
    from bott.skills.connectors import probes

    seen = {}

    def fake_probe(name, subject_email=None):
        seen["subject_email"] = subject_email
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr(probes, "probe", fake_probe)
    _as(client, email="admin@x.com")
    client.post("/api/console/v1/connectors/google/test")
    assert seen["subject_email"] == "admin@x.com"
