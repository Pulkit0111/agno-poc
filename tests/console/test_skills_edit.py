import time

import pytest
from agno.db.sqlite import SqliteDb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bott.interfaces.console import sessions
from bott.interfaces.console.router import build_console_router
from bott.shared.persistence import skills_store


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
    # Same isolated-engine-per-test pattern as tests/console/test_router_skills.py.
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


def _frontmatter(slug, body):
    return f"---\nname: {slug}\ndescription: Does a thing\n---\n\n{body}\n"


def _author(slug="my-skill", author="owner@x.com", content=None):
    content = content if content is not None else _frontmatter(slug, "content v1")
    skills_store.upsert_skill(slug, "My Skill", "Does a thing", content, author, time.time())


# ── PUT (edit) ───────────────────────────────────────────────────────────────────────

def test_owner_can_edit(client, skills_dir):
    _author(author="owner@x.com")
    _as(client, email="owner@x.com")
    r = client.put("/api/console/v1/skills/my-skill",
                    json={"content": _frontmatter("my-skill", "v2"), "note": "tweak"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["version"], int)


def test_non_owner_member_is_403(client, skills_dir):
    _author(author="owner@x.com")
    _as(client, email="someone-else@x.com", admin=False)
    r = client.put("/api/console/v1/skills/my-skill",
                    json={"content": _frontmatter("my-skill", "v2"), "note": "tweak"})
    assert r.status_code == 403


def test_admin_can_edit_anyones_skill(client, skills_dir):
    _author(author="owner@x.com")
    _as(client, email="admin@x.com", admin=True)
    r = client.put("/api/console/v1/skills/my-skill",
                    json={"content": _frontmatter("my-skill", "v2"), "note": "admin edit"})
    assert r.status_code == 200


def test_empty_content_is_422(client, skills_dir):
    _author(author="owner@x.com")
    _as(client, email="owner@x.com")
    r = client.put("/api/console/v1/skills/my-skill", json={"content": "   ", "note": "tweak"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["code"] == "missing_field"
    row = skills_store.get_skill("my-skill")
    assert row["content"] == _frontmatter("my-skill", "content v1")
    assert skills_store.versions("my-skill") == []


def test_built_in_edit_is_409(client, skills_dir):
    _as(client, email="anyone@x.com")
    r = client.put("/api/console/v1/skills/greeter", json={"content": "v2", "note": "n"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"]["code"] == "built_in"


def test_unknown_slug_edit_is_404(client, skills_dir):
    _as(client, email="anyone@x.com")
    r = client.put("/api/console/v1/skills/does-not-exist", json={"content": "v2", "note": "n"})
    assert r.status_code == 404


def test_edit_appends_version_row_and_get_returns_it(client, skills_dir):
    _author(author="owner@x.com")
    _as(client, email="owner@x.com")
    v2 = _frontmatter("my-skill", "v2")
    r = client.put("/api/console/v1/skills/my-skill", json={"content": v2, "note": "second pass"})
    version_id = r.json()["version"]

    detail = client.get("/api/console/v1/skills/my-skill").json()
    assert detail["content"] == v2
    assert len(detail["versions"]) == 1
    assert detail["versions"][0]["id"] == version_id
    assert detail["versions"][0]["note"] == "second pass"
    assert detail["versions"][0]["author"] == "owner@x.com"

    # A second edit appends rather than replaces, and the response's version id is the
    # id captured inside update_content's own INSERT (not a re-query that could race).
    v3 = _frontmatter("my-skill", "v3")
    r3 = client.put("/api/console/v1/skills/my-skill", json={"content": v3, "note": "third"})
    detail2 = client.get("/api/console/v1/skills/my-skill").json()
    assert len(detail2["versions"]) == 2
    assert detail2["content"] == v3
    assert r3.json()["version"] == detail2["versions"][0]["id"]
    assert r3.json()["version"] != version_id


def test_builtin_detail_returns_file_content_and_no_versions(client, skills_dir):
    _as(client, email="anyone@x.com")
    detail = client.get("/api/console/v1/skills/greeter").json()
    assert detail["built_in"] is True
    assert "Say hello warmly." in detail["content"]
    assert detail["versions"] == []


# ── draft ─────────────────────────────────────────────────────────────────────────────

_GOOD_DRAFT = (
    '{"slug": "new-thing", "name": "New Thing", "description": "when to use it", '
    '"content": "# New Thing\\n\\n**When to use:** always\\n\\n## Steps\\n1. Do it\\n\\n'
    '## Done means\\n- Done"}'
)


def test_draft_endpoint_returns_parsed_dict(client, monkeypatch):
    from bott.skills import skill_draft
    monkeypatch.setattr(skill_draft, "_complete", lambda prompt: _GOOD_DRAFT)
    _as(client, email="anyone@x.com")
    r = client.post("/api/console/v1/skills/draft", json={"what": "do a thing", "when": "always"})
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "new-thing"
    assert body["name"] == "New Thing"
    assert "## Steps" in body["content"]


def test_draft_endpoint_retries_once_on_bad_json(client, monkeypatch):
    from bott.skills import skill_draft
    calls = {"n": 0}

    def fake_complete(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json at all"
        return _GOOD_DRAFT

    monkeypatch.setattr(skill_draft, "_complete", fake_complete)
    _as(client, email="anyone@x.com")
    r = client.post("/api/console/v1/skills/draft", json={"what": "do a thing", "when": "always"})
    assert r.status_code == 200
    assert r.json()["slug"] == "new-thing"
    assert calls["n"] == 2


def test_draft_endpoint_502s_after_two_bad_parses(client, monkeypatch):
    from bott.skills import skill_draft
    monkeypatch.setattr(skill_draft, "_complete", lambda prompt: "still not json")
    _as(client, email="anyone@x.com")
    r = client.post("/api/console/v1/skills/draft", json={"what": "do a thing", "when": "always"})
    assert r.status_code == 502
    assert r.json()["detail"]["error"]["code"] == "draft_failed"


# ── create (save from draft) + round-trip ──────────────────────────────────────────────

def test_save_then_get_round_trips(client, skills_dir):
    _as(client, email="author@x.com")
    r = client.post("/api/console/v1/skills", json={
        "slug": "brand-new", "name": "Brand New", "description": "does new things",
        "content": "# Brand New\n\n**When to use:** now\n\n## Steps\n1. Go\n\n## Done means\n- Done",
    })
    assert r.status_code == 200
    slug = r.json()["slug"]
    assert slug == "brand-new"

    detail = client.get(f"/api/console/v1/skills/{slug}").json()
    assert detail["built_in"] is False
    assert detail["authored_by"] == "author@x.com"
    assert "## Steps" in detail["content"]
    assert len(detail["versions"]) == 1  # creation itself is logged as the first version


def test_create_refuses_builtin_name_collision(client, skills_dir):
    _as(client, email="author@x.com")
    r = client.post("/api/console/v1/skills", json={
        "slug": "greeter", "name": "Greeter", "description": "d", "content": "c",
    })
    assert r.status_code == 409
    assert r.json()["detail"]["error"]["code"] == "built_in"


def test_create_refuses_slug_taken_by_another_author(client, skills_dir):
    _author(slug="taken", author="first@x.com")
    _as(client, email="second@x.com")
    r = client.post("/api/console/v1/skills", json={
        "slug": "taken", "name": "Taken", "description": "d", "content": "c",
    })
    assert r.status_code == 409
    assert r.json()["detail"]["error"]["code"] == "slug_taken"


def test_create_same_author_can_recreate_own_slug(client, skills_dir):
    _as(client, email="author@x.com")
    body = {"slug": "mine", "name": "Mine", "description": "d1", "content": "c1"}
    assert client.post("/api/console/v1/skills", json=body).status_code == 200
    body["description"] = "d2"
    r = client.post("/api/console/v1/skills", json=body)
    assert r.status_code == 200
    detail = client.get("/api/console/v1/skills/mine").json()
    # The re-POST updated content but did NOT stack another "Created" version row —
    # only a genuinely new skill logs the initial version.
    assert "d2" in detail["content"]
    assert len(detail["versions"]) == 1
    assert detail["versions"][0]["note"] == "Created"
