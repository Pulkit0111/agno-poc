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
    # Exact pattern proven in tests/test_queue.py's `engine` fixture and reused verbatim
    # in tests/console/test_read_helpers.py: a fresh SQLite file per test via
    # AGENTOS_DB_PATH (or a shared TEST_DATABASE_URL Postgres if the suite sets one).
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


def test_list_is_scoped_to_caller(client):
    import time

    from bott.shared.persistence import action_items
    action_items.add_item("m@x.com", "mine", time.time())
    action_items.add_item("other@x.com", "not mine", time.time())
    _as(client, "m@x.com")
    items = client.get("/api/console/v1/action-items").json()["items"]
    assert [i["text"] for i in items] == ["mine"]


def test_done_marks_complete(client):
    import time

    from bott.shared.persistence import action_items
    iid = action_items.add_item("m@x.com", "task", time.time())
    _as(client, "m@x.com")
    assert client.post(f"/api/console/v1/action-items/{iid}/done").json() == {"status": "done"}
    assert client.get("/api/console/v1/action-items").json()["items"] == []


def test_done_wrong_owner_is_404(client):
    import time

    from bott.shared.persistence import action_items
    iid = action_items.add_item("other@x.com", "task", time.time())
    _as(client, "m@x.com")
    r = client.post(f"/api/console/v1/action-items/{iid}/done")
    assert r.status_code == 404


def test_snooze_default_is_24h(client):
    import time

    from bott.shared.persistence import action_items
    iid = action_items.add_item("m@x.com", "task", time.time())
    _as(client, "m@x.com")
    r = client.post(f"/api/console/v1/action-items/{iid}/snooze", json={})
    assert r.status_code == 200
    assert r.json()["remind_at"] > time.time() + 86000
