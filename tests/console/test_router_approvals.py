import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import bott.interfaces.console.router as router_mod
from bott.interfaces.console import sessions
from bott.interfaces.console.router import build_console_router


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "t3st")


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(build_console_router())
    return TestClient(app)


def _as(client, email, is_admin=False):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, is_admin))


ROW = {"id": 7, "user_id": "m@x.com", "action": "api:jira", "summary": "Comment on AXL-142",
       "status": "pending", "decided_by": None, "payload": "{}", "created": 1.0}


def test_list_mine(client, monkeypatch):
    monkeypatch.setattr(router_mod.approvals, "pending_for",
                        lambda uid, limit=50: [{"id": 7, "action": "api:jira",
                                                "summary": "s", "created": 1.0}])
    _as(client, "m@x.com")
    body = client.get("/api/console/v1/approvals").json()
    assert body["approvals"][0]["user_id"] == "m@x.com"  # normalized in


def test_scope_all_requires_admin(client, monkeypatch):
    monkeypatch.setattr(router_mod.approvals, "pending_all", lambda limit=50: [ROW])
    _as(client, "m@x.com")
    assert client.get("/api/console/v1/approvals?scope=all").status_code == 403
    _as(client, "adm@x.com", is_admin=True)
    assert client.get("/api/console/v1/approvals?scope=all").json()["approvals"] == [ROW]


def test_detail_owner_or_admin_only(client, monkeypatch):
    monkeypatch.setattr(router_mod.approvals, "get_request", lambda i: dict(ROW))
    _as(client, "other@x.com")
    assert client.get("/api/console/v1/approvals/7").status_code == 403
    _as(client, "m@x.com")
    assert client.get("/api/console/v1/approvals/7").json()["summary"] == "Comment on AXL-142"


def test_decision_approve_dispatches_api(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(router_mod.approvals, "get_request", lambda i: dict(ROW))
    monkeypatch.setattr(router_mod.approvals, "decide",
                        lambda i, approved, decided_by: seen.update(d=(i, approved, decided_by)))
    monkeypatch.setattr(router_mod, "_dispatch_api", lambda i: seen.update(api=i))
    _as(client, "m@x.com")
    r = client.post("/api/console/v1/approvals/7/decision", json={"approve": True})
    assert r.json() == {"status": "approved"}
    assert seen["d"] == (7, True, "m@x.com")
    assert seen["api"] == 7


def test_decision_approve_build_dispatches_build(client, monkeypatch):
    row = dict(ROW, action="build:moodflix")
    seen = {}
    monkeypatch.setattr(router_mod.approvals, "get_request", lambda i: row)
    monkeypatch.setattr(router_mod.approvals, "decide", lambda *a, **k: None)
    monkeypatch.setattr(router_mod, "_dispatch_build", lambda i: seen.update(build=i))
    _as(client, "m@x.com")
    client.post("/api/console/v1/approvals/7/decision", json={"approve": True})
    assert seen["build"] == 7


def test_decision_already_decided_is_409(client, monkeypatch):
    monkeypatch.setattr(router_mod.approvals, "get_request",
                        lambda i: dict(ROW, status="approved"))
    _as(client, "m@x.com")
    r = client.post("/api/console/v1/approvals/7/decision", json={"approve": False})
    assert r.status_code == 409
    assert r.json()["detail"]["error"]["code"] == "already_decided"


def test_decision_missing_is_404(client, monkeypatch):
    monkeypatch.setattr(router_mod.approvals, "get_request", lambda i: None)
    _as(client, "m@x.com")
    assert client.post("/api/console/v1/approvals/9/decision", json={"approve": True}).status_code == 404
