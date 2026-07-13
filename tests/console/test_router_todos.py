"""Console todos endpoints: session-scoped CRUD + the isolation gate (user A cannot
toggle/delete user B's todo -> 404). Same fixture conventions as
test_router_action_items.py — not forked."""

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


def test_list_requires_auth(client):
    r = client.get("/api/console/v1/todos")
    assert r.status_code == 401


def test_create_and_list(client):
    _as(client)
    r = client.post("/api/console/v1/todos", json={"text": "Reply to Ankit's comment"})
    assert r.status_code == 200
    tid = r.json()["id"]
    items = client.get("/api/console/v1/todos").json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row == {"id": tid, "text": "Reply to Ankit's comment", "done": False, "created": row["created"]}


def test_list_is_scoped_to_caller(client):
    _as(client, "m@x.com")
    client.post("/api/console/v1/todos", json={"text": "mine"})
    _as(client, "other@x.com")
    client.post("/api/console/v1/todos", json={"text": "not mine"})
    _as(client, "m@x.com")
    items = client.get("/api/console/v1/todos").json()["items"]
    assert [i["text"] for i in items] == ["mine"]


def test_toggle_marks_done(client):
    _as(client)
    tid = client.post("/api/console/v1/todos", json={"text": "task"}).json()["id"]
    r = client.post(f"/api/console/v1/todos/{tid}/toggle", json={"done": True})
    assert r.status_code == 200
    items = client.get("/api/console/v1/todos").json()["items"]
    assert items[0]["done"] is True


def test_toggle_can_untoggle(client):
    _as(client)
    tid = client.post("/api/console/v1/todos", json={"text": "task"}).json()["id"]
    client.post(f"/api/console/v1/todos/{tid}/toggle", json={"done": True})
    client.post(f"/api/console/v1/todos/{tid}/toggle", json={"done": False})
    items = client.get("/api/console/v1/todos").json()["items"]
    assert items[0]["done"] is False


def test_delete_removes_todo(client):
    _as(client)
    tid = client.post("/api/console/v1/todos", json={"text": "task"}).json()["id"]
    r = client.delete(f"/api/console/v1/todos/{tid}")
    assert r.status_code == 200
    assert client.get("/api/console/v1/todos").json()["items"] == []


def test_clear_done_removes_only_done(client):
    _as(client)
    open_id = client.post("/api/console/v1/todos", json={"text": "still open"}).json()["id"]
    done_id = client.post("/api/console/v1/todos", json={"text": "finished"}).json()["id"]
    client.post(f"/api/console/v1/todos/{done_id}/toggle", json={"done": True})
    r = client.post("/api/console/v1/todos/clear-done")
    assert r.status_code == 200
    items = client.get("/api/console/v1/todos").json()["items"]
    assert [i["id"] for i in items] == [open_id]


# ---------------------------------------------------------------------------
# Isolation gate: user A cannot toggle/delete user B's todo -> 404
# ---------------------------------------------------------------------------

def test_toggle_wrong_owner_is_404(client):
    _as(client, "other@x.com")
    tid = client.post("/api/console/v1/todos", json={"text": "belongs to other"}).json()["id"]
    _as(client, "m@x.com")
    r = client.post(f"/api/console/v1/todos/{tid}/toggle", json={"done": True})
    assert r.status_code == 404


def test_delete_wrong_owner_is_404(client):
    _as(client, "other@x.com")
    tid = client.post("/api/console/v1/todos", json={"text": "belongs to other"}).json()["id"]
    _as(client, "m@x.com")
    r = client.delete(f"/api/console/v1/todos/{tid}")
    assert r.status_code == 404


def test_wrong_owner_toggle_leaves_todo_unchanged(client):
    _as(client, "other@x.com")
    tid = client.post("/api/console/v1/todos", json={"text": "belongs to other"}).json()["id"]
    _as(client, "m@x.com")
    client.post(f"/api/console/v1/todos/{tid}/toggle", json={"done": True})
    _as(client, "other@x.com")
    items = client.get("/api/console/v1/todos").json()["items"]
    assert items[0]["done"] is False
