import pytest


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    import os
    from bott.shared import db
    from bott.shared.schema import init_schema
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        monkeypatch.setenv("DATABASE_URL", url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "agentos.db"))
    db.get_engine(fresh=True)
    init_schema()


def test_set_then_get():
    from bott.shared import policy_overrides
    policy_overrides.set_override("jira", "PUT", "gate", "be careful", "a@x.com")
    row = policy_overrides.get_override("jira", "PUT")
    assert row["verdict"] == "gate"
    assert row["reason"] == "be careful"
    assert row["updated_by"] == "a@x.com"


def test_get_missing_is_none():
    from bott.shared import policy_overrides
    assert policy_overrides.get_override("jira", "DELETE") is None


def test_remove_then_get_is_none():
    from bott.shared import policy_overrides
    policy_overrides.set_override("jira", "PUT", "gate", "r", "a@x.com")
    policy_overrides.remove_override("jira", "PUT")
    assert policy_overrides.get_override("jira", "PUT") is None


def test_list_overrides_excludes_removed():
    from bott.shared import policy_overrides
    policy_overrides.set_override("jira", "PUT", "gate", "r1", "a@x.com")
    policy_overrides.set_override("github", "POST", "deny", "r2", "a@x.com")
    policy_overrides.remove_override("github", "POST")
    rows = policy_overrides.list_overrides()
    assert len(rows) == 1
    assert rows[0]["system"] == "jira" and rows[0]["method"] == "PUT"
