"""Admin observability panel — unit + round-trip tests.

Covers:
- recent_jobs / job_counts against a temp SQLite DB
- approvals.pending / pending_count against a temp SQLite DB
- admin_section(is_admin=False) returns []
- admin_section(is_admin=True) returns blocks with job/approval/model info
"""

from __future__ import annotations

import pytest

from bott.shared import db


# ---------------------------------------------------------------------------
# Shared DB fixture (SQLite in tmp dir, fresh schema)
# ---------------------------------------------------------------------------

@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "admin_test.db"))
    monkeypatch.setenv(
        "BOTT_SECRET_KEY",
        __import__("bott.shared.secrets", fromlist=["generate_key"]).generate_key(),
    )
    monkeypatch.setenv("BOTT_ADMINS", "admin@axelerant.com")
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()
    yield


# ---------------------------------------------------------------------------
# queue.recent_jobs / queue.job_counts round-trip
# ---------------------------------------------------------------------------

def test_recent_jobs_empty(store):
    from bott.shared.persistence import queue
    assert queue.recent_jobs() == []


def test_recent_jobs_returns_newest_first(store):
    from bott.shared.persistence import queue

    jid1 = queue.enqueue("plan", {"x": 1}, user_id="u@x.com")
    jid2 = queue.enqueue("implement", {"x": 2}, user_id="u@x.com")

    rows = queue.recent_jobs(limit=8)
    assert len(rows) == 2
    # Newest first: jid2 > jid1
    assert rows[0]["id"] == jid2
    assert rows[0]["kind"] == "implement"
    assert rows[1]["id"] == jid1
    assert rows[1]["kind"] == "plan"
    # Every row has expected keys
    for r in rows:
        assert {"id", "kind", "status", "attempts", "created"} <= r.keys()


def test_recent_jobs_limit(store):
    from bott.shared.persistence import queue

    for i in range(10):
        queue.enqueue("review", {"n": i}, user_id="u@x.com")

    rows = queue.recent_jobs(limit=3)
    assert len(rows) == 3


def test_job_counts_empty(store):
    from bott.shared.persistence import queue
    assert queue.job_counts() == {}


def test_job_counts_groups_by_status(store):
    from bott.shared.persistence import queue
    from sqlalchemy import text

    queue.enqueue("plan", {}, user_id="u@x.com")
    jid2 = queue.enqueue("implement", {}, user_id="u@x.com")
    jid3 = queue.enqueue("review", {}, user_id="u@x.com")

    # Manually mark one as done and one as failed
    with db.get_engine().begin() as c:
        c.execute(text("UPDATE jobs SET status='done' WHERE id=:id"), {"id": jid2})
        c.execute(text("UPDATE jobs SET status='failed' WHERE id=:id"), {"id": jid3})

    counts = queue.job_counts()
    assert counts.get("pending") == 1
    assert counts.get("done") == 1
    assert counts.get("failed") == 1


# ---------------------------------------------------------------------------
# approvals.pending / pending_count round-trip
# ---------------------------------------------------------------------------

def test_pending_count_empty(store):
    from bott.shared import approvals
    assert approvals.pending_count() == 0


def test_pending_returns_empty_list_when_none(store):
    from bott.shared import approvals
    assert approvals.pending() == []


def test_pending_count_and_list(store):
    from bott.shared import approvals

    aid1 = approvals.create_request("u@x.com", "open_pr", "Open PR #1")
    aid2 = approvals.create_request("u@x.com", "send_email", "Email client")

    assert approvals.pending_count() == 2
    rows = approvals.pending(limit=8)
    assert len(rows) == 2
    # Newest first
    assert rows[0]["id"] == aid2
    assert rows[1]["id"] == aid1
    for r in rows:
        assert {"id", "action", "summary", "created"} <= r.keys()


def test_pending_excludes_decided(store):
    from bott.shared import approvals

    aid1 = approvals.create_request("u@x.com", "open_pr", "Open PR #1")
    aid2 = approvals.create_request("u@x.com", "send_email", "Email client")
    approvals.decide(aid1, approved=True, decided_by="admin@x.com")

    assert approvals.pending_count() == 1
    rows = approvals.pending()
    assert len(rows) == 1
    assert rows[0]["id"] == aid2


def test_pending_limit(store):
    from bott.shared import approvals

    for i in range(10):
        approvals.create_request("u@x.com", "act", f"summary {i}")

    rows = approvals.pending(limit=3)
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# admin_section: non-admin gate
# ---------------------------------------------------------------------------

def test_admin_section_non_admin_returns_empty():
    from bott.interfaces.slack_home.admin import admin_section
    assert admin_section(is_admin=False) == []


# ---------------------------------------------------------------------------
# admin_section: admin view — monkeypatch helpers to canned data
# ---------------------------------------------------------------------------

def test_admin_section_admin_contains_job_info(monkeypatch, store):
    from bott.interfaces.slack_home import admin as _admin_mod
    from bott.shared.persistence import queue as _q_mod
    from bott.shared import approvals as _apr_mod, codex_tokens as _ct_mod
    from bott.interfaces.slack_home import models as _m_mod

    monkeypatch.setattr(_q_mod, "recent_jobs", lambda limit=8: [
        {"id": 5, "kind": "plan", "status": "done", "attempts": 1, "created": 1.0},
        {"id": 4, "kind": "implement", "status": "failed", "attempts": 3, "created": 0.9},
    ])
    monkeypatch.setattr(_q_mod, "job_counts", lambda: {"done": 1, "failed": 1})
    monkeypatch.setattr(_apr_mod, "pending_count", lambda: 2)
    monkeypatch.setattr(_apr_mod, "pending", lambda limit=8: [
        {"id": 2, "action": "open_pr", "summary": "Open PR #42", "created": 2.0},
        {"id": 1, "action": "send_email", "summary": "Email client", "created": 1.0},
    ])
    monkeypatch.setattr(_ct_mod, "is_connected", lambda: True)
    monkeypatch.setattr(_m_mod, "_active", lambda: {
        "provider": "codex", "chat": "gpt-4o", "heavy": "gpt-4o"
    })

    from bott.interfaces.slack_home.admin import admin_section
    blocks = admin_section(is_admin=True)

    assert len(blocks) > 0
    full_text = str(blocks)

    # Jobs should appear
    assert "plan" in full_text
    assert "implement" in full_text

    # Approvals section
    assert "Approvals" in full_text
    assert "open_pr" in full_text
    assert "Open PR #42" in full_text

    # Model status
    assert "codex" in full_text
    assert "gpt-4o" in full_text
    assert "connected" in full_text.lower()


def test_admin_section_admin_header_present(monkeypatch, store):
    """The first block must be the admin header."""
    from bott.shared.persistence import queue as _q_mod
    from bott.shared import approvals as _apr_mod, codex_tokens as _ct_mod
    from bott.interfaces.slack_home import models as _m_mod

    monkeypatch.setattr(_q_mod, "recent_jobs", lambda limit=8: [])
    monkeypatch.setattr(_q_mod, "job_counts", lambda: {})
    monkeypatch.setattr(_apr_mod, "pending_count", lambda: 0)
    monkeypatch.setattr(_apr_mod, "pending", lambda limit=8: [])
    monkeypatch.setattr(_ct_mod, "is_connected", lambda: False)
    monkeypatch.setattr(_m_mod, "_active", lambda: {
        "provider": "bedrock", "chat": "claude-3", "heavy": "claude-3"
    })

    from bott.interfaces.slack_home.admin import admin_section
    blocks = admin_section(is_admin=True)

    assert blocks[0]["type"] == "header"
    header_text = blocks[0]["text"]["text"]
    assert "Admin" in header_text


def test_admin_section_admin_job_counts_summary(monkeypatch, store):
    """Failed/pending counts must surface in the text (not just done)."""
    from bott.shared.persistence import queue as _q_mod
    from bott.shared import approvals as _apr_mod, codex_tokens as _ct_mod
    from bott.interfaces.slack_home import models as _m_mod

    monkeypatch.setattr(_q_mod, "recent_jobs", lambda limit=8: [
        {"id": 1, "kind": "review", "status": "failed", "attempts": 3, "created": 1.0},
    ])
    monkeypatch.setattr(_q_mod, "job_counts", lambda: {"failed": 3, "pending": 1})
    monkeypatch.setattr(_apr_mod, "pending_count", lambda: 0)
    monkeypatch.setattr(_apr_mod, "pending", lambda limit=8: [])
    monkeypatch.setattr(_ct_mod, "is_connected", lambda: False)
    monkeypatch.setattr(_m_mod, "_active", lambda: {
        "provider": "openrouter", "chat": "llama", "heavy": "llama"
    })

    from bott.interfaces.slack_home.admin import admin_section
    blocks = admin_section(is_admin=True)
    full_text = str(blocks)

    assert "failed" in full_text
    assert "pending" in full_text


def test_build_home_view_with_admin_blocks():
    """build_home_view renders admin_blocks after the models section."""
    from bott.interfaces.slack_home import blocks as _blocks

    admin_blk = [{"type": "section", "text": {"type": "mrkdwn", "text": "admin panel here"}}]
    view = _blocks.build_home_view([], admin_blocks=admin_blk)

    assert view["type"] == "home"
    full_text = str(view["blocks"])
    assert "admin panel here" in full_text


def test_build_home_view_no_admin_blocks_for_non_admin():
    """When admin_blocks is empty/None, the view must NOT contain admin content."""
    from bott.interfaces.slack_home import blocks as _blocks

    view = _blocks.build_home_view([], admin_blocks=[])
    full_text = str(view["blocks"])
    assert "admin panel here" not in full_text
