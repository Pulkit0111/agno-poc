import pytest
from agno.db.sqlite import SqliteDb
from fastapi import FastAPI
from fastapi.testclient import TestClient

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


def test_shapes_env_admin_and_member_rows(client, monkeypatch):
    from bott.shared.persistence import records
    monkeypatch.setattr(records, "list_known_users", lambda: [
        {"user_id": "admin@x.com", "last_active": 100.0},
        {"user_id": "m@x.com", "last_active": 90.0},
    ])
    _as(client, email="admin@x.com")  # must authenticate as a REAL admin (BOTT_ADMINS above)
    rows = client.get("/api/console/v1/users").json()["users"]
    assert rows == [
        {"email": "admin@x.com", "role": "admin", "locked": True, "invited": False, "last_active": 100.0},
        {"email": "m@x.com", "role": "member", "locked": False, "invited": False, "last_active": 90.0},
    ]
