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
def client(tmp_path):
    from agno.db.sqlite import SqliteDb
    app = FastAPI()
    db = SqliteDb(db_file=str(tmp_path / "console-test.db"))
    app.include_router(build_console_router(db))
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
                        lambda i, approved, decided_by: seen.update(d=(i, approved, decided_by)) or True)
    monkeypatch.setattr(router_mod, "_dispatch_api", lambda i: seen.update(api=i))
    _as(client, "adm@x.com", is_admin=True)
    r = client.post("/api/console/v1/approvals/7/decision", json={"approve": True})
    assert r.json() == {"status": "approved"}
    assert seen["d"] == (7, True, "adm@x.com")
    assert seen["api"] == 7


def test_decision_approve_build_dispatches_build(client, monkeypatch):
    row = dict(ROW, action="build:moodflix")
    seen = {}
    monkeypatch.setattr(router_mod.approvals, "get_request", lambda i: row)
    monkeypatch.setattr(router_mod.approvals, "decide", lambda *a, **k: True)
    monkeypatch.setattr(router_mod, "_dispatch_build", lambda i: seen.update(build=i))
    _as(client, "adm@x.com", is_admin=True)
    client.post("/api/console/v1/approvals/7/decision", json={"approve": True})
    assert seen["build"] == 7


def test_decision_is_admin_only_even_for_own_request(client, monkeypatch):
    # ROW belongs to m@x.com — the requester deciding their own approval would defeat
    # the human-sign-off gate, so it must be a 403, with no decide/dispatch side effects.
    seen = {}
    monkeypatch.setattr(router_mod.approvals, "get_request", lambda i: dict(ROW))
    monkeypatch.setattr(router_mod.approvals, "decide",
                        lambda *a, **k: seen.update(decided=True) or True)
    monkeypatch.setattr(router_mod, "_dispatch_api", lambda i: seen.update(api=i))
    _as(client, "m@x.com")
    r = client.post("/api/console/v1/approvals/7/decision", json={"approve": True})
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "admin_only"
    assert seen == {}


def test_admin_may_decide_own_request(client, monkeypatch):
    # Single-admin orgs must not deadlock: an admin CAN approve their own request.
    row = dict(ROW, user_id="adm@x.com")
    seen = {}
    monkeypatch.setattr(router_mod.approvals, "get_request", lambda i: row)
    monkeypatch.setattr(router_mod.approvals, "decide", lambda *a, **k: True)
    monkeypatch.setattr(router_mod, "_dispatch_api", lambda i: seen.update(api=i))
    _as(client, "adm@x.com", is_admin=True)
    r = client.post("/api/console/v1/approvals/7/decision", json={"approve": True})
    assert r.json() == {"status": "approved"}
    assert seen["api"] == 7


def test_count_requires_admin(client, monkeypatch):
    monkeypatch.setattr(router_mod.approvals, "pending_count", lambda: 4)
    _as(client, "m@x.com")
    assert client.get("/api/console/v1/approvals/count").status_code == 403


def test_count_admin_returns_pending(client, monkeypatch):
    monkeypatch.setattr(router_mod.approvals, "pending_count", lambda: 4)
    _as(client, "adm@x.com", is_admin=True)
    assert client.get("/api/console/v1/approvals/count").json() == {"pending": 4}


def test_decision_approve_build_returns_job_id(client, monkeypatch):
    row = dict(ROW, action="build:moodflix")
    monkeypatch.setattr(router_mod.approvals, "get_request", lambda i: row)
    monkeypatch.setattr(router_mod.approvals, "decide", lambda *a, **k: True)
    monkeypatch.setattr(router_mod, "_dispatch_build", lambda i: 55)
    _as(client, "adm@x.com", is_admin=True)
    r = client.post("/api/console/v1/approvals/7/decision", json={"approve": True})
    assert r.json() == {"status": "approved", "job_id": 55}


def test_decision_approve_api_has_no_job_id(client, monkeypatch):
    # api:* dispatch runs in a background task with no queued job — response omits job_id.
    monkeypatch.setattr(router_mod.approvals, "get_request", lambda i: dict(ROW))
    monkeypatch.setattr(router_mod.approvals, "decide", lambda *a, **k: True)
    monkeypatch.setattr(router_mod, "_dispatch_api", lambda i: None)
    _as(client, "adm@x.com", is_admin=True)
    r = client.post("/api/console/v1/approvals/7/decision", json={"approve": True})
    assert r.json() == {"status": "approved"}


def test_decision_already_decided_is_409(client, monkeypatch):
    monkeypatch.setattr(router_mod.approvals, "get_request",
                        lambda i: dict(ROW, status="approved"))
    _as(client, "adm@x.com", is_admin=True)
    r = client.post("/api/console/v1/approvals/7/decision", json={"approve": False})
    assert r.status_code == 409
    assert r.json()["detail"]["error"]["code"] == "already_decided"


def test_decision_missing_is_404(client, monkeypatch):
    monkeypatch.setattr(router_mod.approvals, "get_request", lambda i: None)
    _as(client, "adm@x.com", is_admin=True)
    assert client.post("/api/console/v1/approvals/9/decision", json={"approve": True}).status_code == 404


def test_decision_race_lost_is_409_and_no_dispatch(client, monkeypatch):
    # Row still looks pending when read, but the UPDATE flips zero rows (someone
    # else won the race) — decide() returning False must block dispatch.
    seen = {}
    monkeypatch.setattr(router_mod.approvals, "get_request", lambda i: dict(ROW))
    monkeypatch.setattr(router_mod.approvals, "decide", lambda *a, **k: False)
    monkeypatch.setattr(router_mod, "_dispatch_api", lambda i: seen.update(api=i))
    monkeypatch.setattr(router_mod, "_dispatch_build", lambda i: seen.update(build=i))
    _as(client, "adm@x.com", is_admin=True)
    r = client.post("/api/console/v1/approvals/7/decision", json={"approve": True})
    assert r.status_code == 409
    assert r.json()["detail"]["error"]["code"] == "already_decided"
    assert seen == {}
