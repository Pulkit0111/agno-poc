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


def _as(client, email="m@x.com"):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, False))


def _as_admin(client, email="admin@x.com"):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, True))


def test_security_report(client, monkeypatch):
    import bott.skills.advisories as advisories
    monkeypatch.setattr(advisories, "drupal_security_advisories", lambda: "no advisories")
    _as_admin(client)
    r = client.post("/api/console/v1/reports/run", json={"kind": "security"})
    assert r.json() == {"result": "no advisories"}


def test_sprint_snapshot_requires_engagement(client):
    _as_admin(client)
    r = client.post("/api/console/v1/reports/run", json={"kind": "sprint_snapshot"})
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "missing_field"


def test_sprint_snapshot_with_engagement(client, monkeypatch):
    import bott.skills.sprint_report.tool as tool
    monkeypatch.setattr(tool, "sprint_snapshot", lambda eng: f"snapshot for {eng}")
    _as_admin(client)
    r = client.post("/api/console/v1/reports/run", json={"kind": "sprint_snapshot", "engagement": "acme"})
    assert r.json() == {"result": "snapshot for acme"}


def test_standup_open_requires_team_and_channel(client):
    _as_admin(client)
    r = client.post("/api/console/v1/reports/run", json={"kind": "standup_open"})
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "missing_field"


def test_unknown_kind_is_400(client):
    _as_admin(client)
    r = client.post("/api/console/v1/reports/run", json={"kind": "nonsense"})
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "bad_kind"


def test_non_admin_cannot_run_reports(client):
    """Regression: this endpoint used to be reachable by any authenticated user, letting a
    non-admin trigger org-wide reports or post standup messages into arbitrary channels."""
    _as(client)
    r = client.post("/api/console/v1/reports/run", json={"kind": "security"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "admin_only"
