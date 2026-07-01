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


def test_build_agent_includes_skill_authoring(dbenv, monkeypatch):
    monkeypatch.setattr("bott.shared.config.bott_skills_dir", lambda: str(dbenv / "lib"))
    import bott.agents.bott_agent as ba
    agent = ba.build_agent("alice@axelerant.com", db=None)
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in agent.tools}
    assert {"author_skill", "list_skills", "retire_skill"} <= names


def test_materialize_on_empty_db_is_noop(dbenv):
    assert store.materialize_to_fs(str(dbenv / "lib")) == 0


def test_startup_sequence_restores_authored_skill_to_fs(dbenv, monkeypatch):
    # Simulate: a skill was authored in a PRIOR run (row in DB), then the container restarted
    # (empty skills dir). The startup sequence (init_schema already done by fixture) must
    # materialize it back to the FS so LocalSkills can load it.
    store.upsert_skill("prior-skill", "prior-skill", "d",
                       "---\nname: prior-skill\ndescription: d\n---\nbody", "a@x.com", now=1.0)
    lib = dbenv / "lib"
    n = store.materialize_to_fs(str(lib))
    assert n == 1
    assert (lib / "prior-skill" / "SKILL.md").exists()
