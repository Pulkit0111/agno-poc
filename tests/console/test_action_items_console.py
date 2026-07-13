"""Console action-items: create (source-tagged "console") + `source` surfaced in list.
New endpoint coverage alongside the existing list/done/snooze tests in
test_router_action_items.py — same fixture conventions, not forked."""

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
def client(tmp_path, monkeypatch):
    import os

    from bott.shared import db as db_mod
    from bott.shared.schema import init_schema
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        monkeypatch.setenv("DATABASE_URL", url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "agentos.db"))
    db_mod.get_engine(fresh=True)
    init_schema()
    app = FastAPI()
    app.include_router(build_console_router(SqliteDb(db_file=str(tmp_path / "s.db"))))
    return TestClient(app)


def _as(client, email="m@x.com"):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, False))


def test_create_sets_source_console(client):
    _as(client)
    r = client.post("/api/console/v1/action-items", json={"text": "Follow up with client"})
    assert r.status_code == 200
    item_id = r.json()["id"]
    items = client.get("/api/console/v1/action-items").json()["items"]
    created = next(i for i in items if i["id"] == item_id)
    assert created["source"] == "console"
    assert created["text"] == "Follow up with client"


def test_create_requires_auth(client):
    r = client.post("/api/console/v1/action-items", json={"text": "nope"})
    assert r.status_code == 401


def test_create_scoped_to_caller(client):
    _as(client, "m@x.com")
    client.post("/api/console/v1/action-items", json={"text": "mine"})
    _as(client, "other@x.com")
    items = client.get("/api/console/v1/action-items").json()["items"]
    assert items == []


def test_list_returns_source_for_agent_created_items(client):
    import time

    from bott.shared.persistence import action_items
    action_items.add_item("m@x.com", "from agent", time.time())  # default source "user"
    _as(client, "m@x.com")
    items = client.get("/api/console/v1/action-items").json()["items"]
    assert items[0]["source"] == "user"


def test_snooze_accepts_explicit_remind_at(client):
    import time

    from bott.shared.persistence import action_items
    iid = action_items.add_item("m@x.com", "task", time.time())
    _as(client, "m@x.com")
    target = time.time() + 3600
    r = client.post(f"/api/console/v1/action-items/{iid}/snooze", json={"remind_at": target})
    assert r.status_code == 200
    assert r.json()["remind_at"] == target
    items = client.get("/api/console/v1/action-items").json()["items"]
    assert items[0]["remind_at"] == target
