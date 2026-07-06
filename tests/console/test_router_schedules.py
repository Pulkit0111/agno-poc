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
def client_and_db(tmp_path):
    app = FastAPI()
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    app.include_router(build_console_router(db))
    return TestClient(app), db


def _as(client, email="m@x.com"):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, False))


def test_list_requires_auth(client_and_db):
    tc, _db = client_and_db
    assert tc.get("/api/console/v1/schedules").status_code == 401


def test_list_and_lifecycle_round_trip(client_and_db):
    from bott.skills import scheduling
    tc, db = client_and_db
    sch = scheduling.create_security_digest(db, channel="#sec", cron="0 9 * * *")
    _as(tc)
    rows = tc.get("/api/console/v1/schedules").json()["schedules"]
    assert rows[0]["id"] == sch.id
    assert tc.post(f"/api/console/v1/schedules/{sch.id}/pause").json() == {"enabled": False}
    assert tc.get("/api/console/v1/schedules").json()["schedules"][0]["enabled"] is False
    assert tc.post(f"/api/console/v1/schedules/{sch.id}/resume").json() == {"enabled": True}


def test_pause_missing_is_404(client_and_db):
    tc, _db = client_and_db
    _as(tc)
    r = tc.post("/api/console/v1/schedules/nope/pause")
    assert r.status_code == 404
    assert r.json()["detail"]["error"]["code"] == "not_found"


def test_run_now_and_delete_do_not_require_existence_check(client_and_db, monkeypatch):
    # run-now proxies to an HTTP endpoint (fire-and-forget in this app's own design) and
    # delete calls remove() which is a no-op on unknown ids — both should just succeed.
    tc, _db = client_and_db
    import bott.interfaces.console.router as router_mod
    monkeypatch.setattr(router_mod.schedule_service, "trigger_now", lambda sid: None)
    _as(tc)
    assert tc.post("/api/console/v1/schedules/anything/run-now").json() == {"triggered": True}
    assert tc.delete("/api/console/v1/schedules/anything").json() == {"deleted": True}


def test_create_security_schedule(client_and_db):
    tc, _db = client_and_db
    _as(tc)
    r = tc.post("/api/console/v1/schedules", json={
        "kind": "security", "channel": "#sec", "frequency": "daily", "time": "09:00",
    })
    assert r.status_code == 200
    assert "id" in r.json()


def test_create_sprint_requires_engagement(client_and_db):
    tc, _db = client_and_db
    _as(tc)
    r = tc.post("/api/console/v1/schedules", json={
        "kind": "sprint", "channel": "#eng", "time": "16:00",
    })
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "missing_field"


def test_create_unknown_kind_is_400(client_and_db):
    tc, _db = client_and_db
    _as(tc)
    r = tc.post("/api/console/v1/schedules", json={
        "kind": "nonsense", "channel": "#x", "time": "09:00",
    })
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "bad_kind"


def test_create_bad_frequency_is_400(client_and_db):
    tc, _db = client_and_db
    _as(tc)
    r = tc.post("/api/console/v1/schedules", json={
        "kind": "portfolio", "channel": "#x", "frequency": "fortnightly", "time": "09:00",
    })
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "bad_frequency"


def test_create_bad_time_is_400(client_and_db):
    tc, _db = client_and_db
    _as(tc)
    r = tc.post("/api/console/v1/schedules", json={
        "kind": "portfolio", "channel": "#x", "frequency": "daily", "time": "9am",
    })
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "bad_time"
