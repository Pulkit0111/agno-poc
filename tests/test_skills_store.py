import pytest

from bott.shared import db, schema
from bott.shared.persistence import skills_store as store


@pytest.fixture
def dbenv(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "s.db"))
    db.get_engine(fresh=True)
    schema.init_schema()
    yield tmp_path


def test_upsert_and_get(dbenv):
    store.upsert_skill("my-skill", "my-skill", "does a thing",
                       "---\nname: my-skill\n---\nbody", "a@x.com", now=100.0)
    row = store.get_skill("my-skill")
    assert row["slug"] == "my-skill" and row["authored_by"] == "a@x.com"
    assert row["description"] == "does a thing" and row["usage_count"] == 1


def test_upsert_updates_and_preserves(dbenv):
    store.upsert_skill("s", "s", "d1", "c1", "a@x.com", now=100.0)
    store.set_pinned("s", True)
    store.upsert_skill("s", "s", "d2", "c2", "a@x.com", now=200.0)
    row = store.get_skill("s")
    assert row["description"] == "d2" and row["content"] == "c2"
    assert row["created"] == 100.0 and row["updated"] == 200.0
    assert row["pinned"] == 1 and row["usage_count"] == 2  # preserved pin, bumped usage


def test_set_pinned_and_delete_missing_return_false(dbenv):
    assert store.set_pinned("nope", True) is False
    assert store.delete_skill("nope") is False


def test_delete_removes(dbenv):
    store.upsert_skill("s", "s", "d", "c", "a@x.com", now=1.0)
    assert store.delete_skill("s") is True
    assert store.get_skill("s") is None


def test_materialize_to_fs(dbenv):
    tmp_path = dbenv
    store.upsert_skill("s", "s", "d", "---\nname: s\ndescription: d\n---\nbody", "a@x.com", now=1.0)
    skills_dir = tmp_path / "lib"
    (skills_dir / "curated").mkdir(parents=True)
    (skills_dir / "curated" / "SKILL.md").write_text("---\nname: curated\n---\n")
    n = store.materialize_to_fs(str(skills_dir))
    assert n == 1
    assert (skills_dir / "s" / "SKILL.md").read_text().startswith("---")
    assert (skills_dir / "curated" / "SKILL.md").exists()  # non-DB dir untouched
