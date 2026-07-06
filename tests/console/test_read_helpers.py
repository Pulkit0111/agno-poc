import os

import pytest
from sqlalchemy import text

from bott.shared import db
from bott.shared import approvals
from bott.shared.persistence import queue


@pytest.fixture(autouse=True)
def _tmp_db(monkeypatch, tmp_path):
    """Mirrors the `engine` fixture in tests/test_queue.py: a fresh SQLite file
    per test via AGENTOS_DB_PATH, or a shared TEST_DATABASE_URL Postgres if set."""
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        monkeypatch.setenv("DATABASE_URL", url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "console.db"))
    db.get_engine(fresh=True)
    approvals.init_approvals()
    queue.init_queue()
    # Start every test with clean tables — a shared Postgres TEST_DATABASE_URL
    # persists rows across tests otherwise.
    with db.get_engine().begin() as c:
        c.execute(text("DELETE FROM approvals"))
        c.execute(text("DELETE FROM jobs"))
    yield


def test_pending_all_includes_user_id():
    approvals.create_request("a@x.com", "api:jira", "Comment on AXL-1")
    approvals.create_request("b@x.com", "build:moodflix", "Fix README")
    rows = approvals.pending_all()
    assert [r["user_id"] for r in rows] == ["b@x.com", "a@x.com"]  # newest first
    assert set(rows[0]) == {"id", "user_id", "action", "summary", "created"}


def test_pending_all_excludes_decided():
    i = approvals.create_request("a@x.com", "api:jira", "x")
    approvals.decide(i, approved=True, decided_by="a@x.com")
    assert approvals.pending_all() == []


def test_job_detail_full_row():
    jid = queue.enqueue("review", {"pr": 4}, user_id="a@x.com")
    row = queue.job_detail(jid)
    assert row["kind"] == "review"
    assert row["user_id"] == "a@x.com"
    assert set(row) == {"id", "kind", "args", "user_id", "status", "attempts", "error", "created"}


def test_job_detail_missing_is_none():
    assert queue.job_detail(999999) is None
