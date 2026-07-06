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


def test_list_requires_admin(client):
    _as(client, admin=False)
    assert client.get("/api/console/v1/policy/overrides").status_code == 403


def test_set_then_list_then_remove(client):
    _as(client)
    assert client.post("/api/console/v1/policy/overrides", json={
        "system": "jira", "method": "PUT", "verdict": "gate", "reason": "careful",
    }).json() == {"set": True}
    rows = client.get("/api/console/v1/policy/overrides").json()["overrides"]
    assert rows == [{"system": "jira", "method": "PUT", "verdict": "gate",
                      "reason": "careful", "updated_by": "m@x.com", "updated_at": rows[0]["updated_at"]}]
    assert client.delete("/api/console/v1/policy/overrides/jira/PUT").json() == {"removed": True}
    assert client.get("/api/console/v1/policy/overrides").json()["overrides"] == []


def test_classify_reflects_override(client, monkeypatch):
    import bott.interfaces.console.router as router_mod
    monkeypatch.setattr(router_mod.action_policy, "classify",
                        lambda system, method: router_mod.action_policy.Decision(verdict="deny", reason="override: test"))
    _as(client)
    r = client.post("/api/console/v1/policy/classify", json={"system": "slack", "method": "x"})
    assert r.json() == {"verdict": "deny", "reason": "override: test"}


def test_repos_is_read_only_list(client, monkeypatch):
    from bott.shared import config
    monkeypatch.setattr(config, "allowed_post_repos", lambda: {"org/repo1", "org/repo2"})
    _as(client)
    r = client.get("/api/console/v1/policy/repos")
    assert set(r.json()["repos"]) == {"org/repo1", "org/repo2"}
