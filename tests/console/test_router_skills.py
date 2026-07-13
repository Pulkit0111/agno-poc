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
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    (d / "greeter").mkdir(parents=True)
    (d / "greeter" / "SKILL.md").write_text(
        "---\nname: greeter\ndescription: Says hello\n---\nSay hello warmly.\n"
    )
    from bott.shared import config
    monkeypatch.setattr(config, "bott_skills_dir", lambda: str(d))
    return d


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isolate the shared SQLAlchemy engine (skills_store rides on it) per test — same
    # pattern as tests/console/test_router_action_items.py's `client` fixture — so
    # skills written/pinned in one test don't leak into the next via the cached engine.
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


def _as(client, email="m@x.com", admin=False):
    client.cookies.set(sessions.COOKIE_NAME, sessions.issue_session(email, admin))
    if admin:
        # is_admin is recomputed live from roles.is_admin (env ∪ KV) on every
        # verify_session call — a real admin source must back the claim.
        import os
        os.environ["BOTT_ADMINS"] = email


def test_list_shows_builtin_skill(client, skills_dir):
    _as(client)
    rows = client.get("/api/console/v1/skills").json()["skills"]
    assert any(r["name"] == "greeter" and r["built_in"] is True for r in rows)


def test_authored_skill_is_not_builtin(client, skills_dir):
    import time

    from bott.shared.persistence import skills_store
    skills_store.upsert_skill("greeter", "greeter", "Says hello", "content", "m@x.com", time.time())
    _as(client)
    rows = client.get("/api/console/v1/skills").json()["skills"]
    row = next(r for r in rows if r["name"] == "greeter")
    assert row["built_in"] is False
    assert row["authored_by"] == "m@x.com"


def test_pin_requires_admin(client, skills_dir):
    import time

    from bott.shared.persistence import skills_store
    skills_store.upsert_skill("greeter", "greeter", "Says hello", "content", "m@x.com", time.time())
    _as(client, admin=False)
    assert client.post("/api/console/v1/skills/greeter/pin", json={"pinned": True}).status_code == 403
    _as(client, admin=True)
    assert client.post("/api/console/v1/skills/greeter/pin", json={"pinned": True}).json() == {"pinned": True}


def test_retire_refuses_builtin(client, skills_dir):
    _as(client, admin=True)
    r = client.post("/api/console/v1/skills/greeter/retire")
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "builtin_protected"


def test_retire_refuses_pinned(client, skills_dir):
    import time

    from bott.shared.persistence import skills_store
    skills_store.upsert_skill("greeter", "greeter", "Says hello", "content", "m@x.com", time.time())
    skills_store.set_pinned("greeter", True)
    _as(client, admin=True)
    r = client.post("/api/console/v1/skills/greeter/retire")
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "pinned_protected"


def test_retire_authored_unpinned_succeeds(client, skills_dir):
    import time

    from bott.shared.persistence import skills_store
    skills_store.upsert_skill("greeter", "greeter", "Says hello", "content", "m@x.com", time.time())
    _as(client, admin=True)
    assert client.post("/api/console/v1/skills/greeter/retire").json() == {"retired": True}
