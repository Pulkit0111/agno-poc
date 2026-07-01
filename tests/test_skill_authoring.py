from types import SimpleNamespace

import pytest

import bott.skills.skill_authoring as sa
from bott.shared import db, schema
from bott.shared.persistence import skills_store as store


class _Skills:
    def __init__(self, names): self._names = set(names)
    def get_skill_names(self): return sorted(self._names)
    def reload(self): pass


@pytest.fixture
def dbenv(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "s.db"))
    db.get_engine(fresh=True)
    schema.init_schema()
    monkeypatch.setattr(sa.config, "bott_skills_dir", lambda: str(tmp_path / "lib"))
    yield tmp_path


def _ctx(uid="admin@x.com"): return SimpleNamespace(user_id=uid)


def test_author_skill_persists_and_reloads(dbenv, monkeypatch):
    skills = _Skills([])
    monkeypatch.setattr(skills, "reload", lambda: skills._names.add("greet-user"))
    out = sa._author_skill_impl(skills, _ctx("a@x.com"), "Greet User", "greets a user", "Say hi.")
    assert "greet-user" in out
    row = store.get_skill("greet-user")
    assert row and row["authored_by"] == "a@x.com"
    assert (dbenv / "lib" / "greet-user" / "SKILL.md").exists()


def test_author_skill_blank_identity_fails_closed(dbenv):
    out = sa._author_skill_impl(_Skills([]), _ctx(None), "X", "d", "body")
    assert "couldn't tell who you are" in out.lower()
    assert store.get_skill("x") is None


def test_author_skill_refuses_builtin_slug(dbenv):
    skills = _Skills(["sprint-report"])  # curated built-in, no DB row
    out = sa._author_skill_impl(skills, _ctx("a@x.com"), "sprint report", "d", "body")
    assert "built-in" in out.lower()
    assert store.get_skill("sprint-report") is None


def test_author_requires_description_and_body(dbenv):
    assert "description" in sa._author_skill_impl(_Skills([]), _ctx("a@x.com"), "n", "", "b").lower()


def test_retire_admin_gated(dbenv, monkeypatch):
    monkeypatch.setattr(sa.config, "bott_admins", lambda: {"admin@x.com"})
    store.upsert_skill("s", "s", "d", "c", "a@x.com", now=1.0)
    out = sa._retire_impl(_Skills(["s"]), _ctx("notadmin@x.com"), "s")
    assert "admin" in out.lower()
    assert store.get_skill("s") is not None


def test_retire_refuses_pinned_and_builtin(dbenv, monkeypatch):
    monkeypatch.setattr(sa.config, "bott_admins", lambda: {"admin@x.com"})
    store.upsert_skill("s", "s", "d", "c", "a@x.com", now=1.0)
    store.set_pinned("s", True)
    skills = _Skills(["s", "sprint-report"])
    assert "pinned" in sa._retire_impl(skills, _ctx("admin@x.com"), "s").lower()
    assert "built-in" in sa._retire_impl(skills, _ctx("admin@x.com"), "sprint-report").lower()


def test_retire_removes_db_and_fs(dbenv, monkeypatch):
    monkeypatch.setattr(sa.config, "bott_admins", lambda: {"admin@x.com"})
    lib = dbenv / "lib"
    store.upsert_skill("s", "s", "d", "c", "a@x.com", now=1.0)
    (lib / "s").mkdir(parents=True); (lib / "s" / "SKILL.md").write_text("x")  # noqa: E702
    out = sa._retire_impl(_Skills(["s"]), _ctx("admin@x.com"), "s")
    assert "retired" in out.lower()
    assert store.get_skill("s") is None and not (lib / "s").exists()


def test_pin_admin_gated(dbenv, monkeypatch):
    monkeypatch.setattr(sa.config, "bott_admins", lambda: {"admin@x.com"})
    store.upsert_skill("s", "s", "d", "c", "a@x.com", now=1.0)
    assert "admin" in sa._pin_impl(_ctx("no@x.com"), "s", True).lower()
    assert store.get_skill("s")["pinned"] == 0


def test_pin_admin_case_insensitive(dbenv, monkeypatch):
    monkeypatch.setattr(sa.config, "bott_admins", lambda: {"admin@x.com"})  # stored lowercase
    store.upsert_skill("s", "s", "d", "c", "a@x.com", now=1.0)
    out = sa._pin_impl(_ctx("Admin@X.com"), "s", True)  # uppercase actor
    assert "pinned" in out.lower()
    assert store.get_skill("s")["pinned"] == 1


def test_tools_family_gates_on_skills():
    assert sa.skill_authoring_tools(skills=None) == []
    tools = sa.skill_authoring_tools(skills=_Skills([]))
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in tools}
    assert {"author_skill", "list_skills", "pin_skill", "unpin_skill", "retire_skill"} <= names
