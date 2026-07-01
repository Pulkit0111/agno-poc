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
