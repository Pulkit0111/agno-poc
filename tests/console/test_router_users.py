import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agno.db.sqlite import SqliteDb

import bott.interfaces.console.router as router_mod
from bott.interfaces.console import sessions
from bott.interfaces.console.router import build_console_router


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CONSOLE_SESSION_SECRET", "t3st")
    monkeypatch.setenv("BOTT_ADMINS", "admin@x.com")


@pytest.fixture()
def client(tmp_path):
    app = FastAPI()
    app.include_router(build_console_router(SqliteDb(db_file=str(tmp_path / "s.db"))))
    return TestClient(app)


def _as(client, email="m@x.com", admin=True):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, admin))


def test_requires_admin(client):
    _as(client, admin=False)
    assert client.get("/api/console/v1/users").status_code == 403


def test_tags_admin_flag(client, monkeypatch):
    from bott.shared.persistence import records
    monkeypatch.setattr(records, "list_known_users", lambda: [
        {"user_id": "admin@x.com", "last_active": 100.0},
        {"user_id": "m@x.com", "last_active": 90.0},
    ])
    _as(client)
    rows = client.get("/api/console/v1/users").json()["users"]
    assert rows == [
        {"user_id": "admin@x.com", "last_active": 100.0, "is_admin": True},
        {"user_id": "m@x.com", "last_active": 90.0, "is_admin": False},
    ]
