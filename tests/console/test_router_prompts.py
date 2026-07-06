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
def client(tmp_path, monkeypatch):
    # Exact pattern proven in tests/test_queue.py's `engine` fixture and reused verbatim
    # in tests/console/test_router_action_items.py: a fresh SQLite file per test via
    # AGENTOS_DB_PATH (or a shared TEST_DATABASE_URL Postgres if the suite sets one).
    # Needed here because prompts_store uses get_engine() internally (not the injected
    # agno db), so its table must exist in that engine's fresh per-test database.
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


def _as(client, email="m@x.com", admin=True):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, admin))


def test_get_requires_admin(client):
    _as(client, admin=False)
    assert client.get("/api/console/v1/prompts/identity").status_code == 403


def test_get_bad_name_is_400(client):
    _as(client)
    r = client.get("/api/console/v1/prompts/nonsense")
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "bad_name"


def test_get_falls_back_to_constant(client):
    from bott.agents import personality
    _as(client)
    body = client.get("/api/console/v1/prompts/identity").json()
    assert body["current"] == personality.IDENTITY
    assert body["versions"] == []


def test_save_then_get_reflects_new_version(client):
    _as(client)
    r = client.post("/api/console/v1/prompts/voice", json={"content": "new voice", "note": "tweak"})
    assert r.status_code == 200
    vid = r.json()["id"]
    body = client.get("/api/console/v1/prompts/voice").json()
    assert body["current"] == "new voice"
    assert body["versions"][0]["id"] == vid


def test_save_requires_admin(client):
    _as(client, admin=False)
    r = client.post("/api/console/v1/prompts/voice", json={"content": "x", "note": "n"})
    assert r.status_code == 403


def test_revert_creates_new_version_copying_old_content(client):
    _as(client)
    v1 = client.post("/api/console/v1/prompts/voice", json={"content": "v1", "note": "n1"}).json()["id"]
    client.post("/api/console/v1/prompts/voice", json={"content": "v2", "note": "n2"})
    r = client.post(f"/api/console/v1/prompts/voice/revert/{v1}")
    assert r.status_code == 200
    body = client.get("/api/console/v1/prompts/voice").json()
    assert body["current"] == "v1"
    assert len(body["versions"]) == 3  # v1, v2, and the new revert-version


def test_revert_missing_version_is_404(client):
    _as(client)
    r = client.post("/api/console/v1/prompts/voice/revert/999999")
    assert r.status_code == 404
