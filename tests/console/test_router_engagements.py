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
def client_and_db(tmp_path):
    app = FastAPI()
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    app.include_router(build_console_router(db))
    return TestClient(app), db


def _as(client, email="m@x.com", admin=True):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, admin))
    if admin:
        # is_admin is recomputed live from roles.is_admin (env ∪ KV) on every
        # verify_session call — a real admin source must back the claim.
        import os
        os.environ["BOTT_ADMINS"] = email


def test_list_requires_admin(client_and_db):
    tc, _db = client_and_db
    _as(tc, admin=False)
    assert tc.get("/api/console/v1/engagements").status_code == 403


def test_list_includes_schedule_count(client_and_db, monkeypatch):
    tc, _db = client_and_db
    import bott.interfaces.console.router as router_mod
    from bott.skills import channel_map
    monkeypatch.setattr(channel_map, "list_all", lambda: [{"channel_id": "C1", "engagement": "acme"}])
    monkeypatch.setattr(router_mod.schedule_service, "list_raw", lambda db: [
        {"id": "s1", "channel": "C1"}, {"id": "s2", "channel": "C1"}, {"id": "s3", "channel": "C2"},
    ])
    _as(tc)
    rows = tc.get("/api/console/v1/engagements").json()["engagements"]
    assert rows == [{"channel_id": "C1", "engagement": "acme", "schedule_count": 2}]


def test_map_requires_admin(client_and_db):
    tc, _db = client_and_db
    _as(tc, admin=False)
    r = tc.post("/api/console/v1/engagements", json={"channel_id": "C1", "engagement": "acme"})
    assert r.status_code == 403


def test_map_then_unmap(client_and_db):
    tc, _db = client_and_db
    _as(tc)
    assert tc.post("/api/console/v1/engagements", json={"channel_id": "C1", "engagement": "acme"}).json() == {"mapped": True}
    from bott.skills import channel_map
    assert channel_map.list_all() == [{"channel_id": "C1", "engagement": "acme"}]
    assert tc.delete("/api/console/v1/engagements/C1").json() == {"unmapped": True}
    assert channel_map.list_all() == []
