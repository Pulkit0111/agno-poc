import time

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


def test_save_and_latest(store=None):
    from bott.shared.persistence import prompts_store
    now = time.time()
    vid = prompts_store.save_version("identity", "v1 content", "first save", "a@x.com", now)
    assert isinstance(vid, int)
    row = prompts_store.latest("identity")
    assert row["content"] == "v1 content"
    assert row["id"] == vid


def test_latest_returns_none_when_no_versions():
    from bott.shared.persistence import prompts_store
    assert prompts_store.latest("voice") is None


def test_list_versions_newest_first():
    from bott.shared.persistence import prompts_store
    now = time.time()
    prompts_store.save_version("voice", "v1", "n1", "a@x.com", now)
    prompts_store.save_version("voice", "v2", "n2", "a@x.com", now + 1)
    rows = prompts_store.list_versions("voice")
    assert [r["content"] for r in rows] == ["v2", "v1"]


def test_versions_are_scoped_by_prompt_name():
    from bott.shared.persistence import prompts_store
    now = time.time()
    prompts_store.save_version("identity", "id-content", "n", "a@x.com", now)
    prompts_store.save_version("voice", "voice-content", "n", "a@x.com", now)
    assert prompts_store.latest("identity")["content"] == "id-content"
    assert prompts_store.latest("voice")["content"] == "voice-content"


def test_get_version_by_id():
    from bott.shared.persistence import prompts_store
    vid = prompts_store.save_version("identity", "content", "note", "a@x.com", time.time())
    row = prompts_store.get_version(vid)
    assert row["note"] == "note"


def test_get_version_missing_is_none():
    from bott.shared.persistence import prompts_store
    assert prompts_store.get_version(999999) is None
