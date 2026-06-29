"""Tests for bott.shared.persistence.records — settings KV, dedup, review traces.

Uses the default SQLite test engine (same pattern as test_approvals.py): a tmp AGENTOS_DB_PATH
+ db.get_engine(fresh=True) + init_schema() so no Postgres is required for the standard suite.
The live-PG run (Step 6) exercises the same tests against a real Postgres via TEST_DATABASE_URL.
"""

import os

import pytest

from bott.shared import db
from bott.shared.persistence import records
from bott.shared.schema import init_schema


@pytest.fixture
def store(monkeypatch, tmp_path):
    # Clear DATABASE_URL so get_engine() builds a SQLite engine for the standard run.
    # When TEST_DATABASE_URL is set (the live-PG step), it is mapped to DATABASE_URL
    # by the caller, so this monkeypatch removes only the absence case.
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        monkeypatch.setenv("DATABASE_URL", test_url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "rec.db"))
    db.get_engine(fresh=True)
    init_schema()
    yield
    db.get_engine(fresh=True)  # reset engine so later tests start clean


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def test_get_setting_missing_returns_default(store):
    assert records.get_setting("no_such_key") is None
    assert records.get_setting("no_such_key", default="fallback") == "fallback"


def test_set_and_get_setting(store):
    records.set_setting("my_key", "hello")
    assert records.get_setting("my_key") == "hello"


def test_set_setting_upserts(store):
    records.set_setting("dup_key", "first")
    records.set_setting("dup_key", "second")
    assert records.get_setting("dup_key") == "second"


# ---------------------------------------------------------------------------
# seen_delivery
# ---------------------------------------------------------------------------

def test_seen_delivery_first_is_false(store):
    assert records.seen_delivery("d-abc") is False


def test_seen_delivery_second_is_true(store):
    records.seen_delivery("d-dup")
    assert records.seen_delivery("d-dup") is True


def test_seen_delivery_different_ids(store):
    assert records.seen_delivery("d-x") is False
    assert records.seen_delivery("d-y") is False


def test_seen_delivery_empty_is_false(store):
    assert records.seen_delivery("") is False


# ---------------------------------------------------------------------------
# seen_commit
# ---------------------------------------------------------------------------

def test_seen_commit_first_is_false(store):
    assert records.seen_commit("owner", "repo", "abc123") is False


def test_seen_commit_dedup(store):
    records.seen_commit("owner", "repo", "sha1")
    assert records.seen_commit("owner", "repo", "sha1") is True


def test_seen_commit_different_sha_is_false(store):
    records.seen_commit("owner", "repo", "shaA")
    assert records.seen_commit("owner", "repo", "shaB") is False


def test_seen_commit_missing_parts_is_false(store):
    assert records.seen_commit("", "repo", "sha") is False
    assert records.seen_commit("owner", "", "sha") is False
    assert records.seen_commit("owner", "repo", "") is False


# ---------------------------------------------------------------------------
# save_trace + latest_trace_for_thread
# ---------------------------------------------------------------------------

def test_save_trace_returns_int(store):
    tid = records.save_trace(
        channel="C1", thread_ts="t1", owner="o", name="r", pr_number=7,
        original_verdict="approve", final_verdict="approve",
        output_json="{}", gate_json="{}",
    )
    assert isinstance(tid, int) and tid > 0


def test_latest_trace_for_thread_returns_row(store):
    records.save_trace(
        channel="C2", thread_ts="t2", owner="ox", name="rx", pr_number=42,
        original_verdict="issues", final_verdict="suggestions",
        output_json='{"x":1}', gate_json='{"g":1}',
    )
    row = records.latest_trace_for_thread("C2", "t2")
    assert row is not None
    assert row["pr_number"] == 42
    assert row["final_verdict"] == "suggestions"
    assert row["owner"] == "ox"
    assert row["name"] == "rx"


def test_latest_trace_for_thread_unknown_returns_none(store):
    assert records.latest_trace_for_thread("CNOPE", "tNOPE") is None


def test_latest_trace_returns_newest(store):
    records.save_trace(
        channel="C3", thread_ts="t3", owner="o", name="r", pr_number=1,
        original_verdict="approve", final_verdict="approve",
        output_json="{}", gate_json="{}",
    )
    records.save_trace(
        channel="C3", thread_ts="t3", owner="o", name="r", pr_number=2,
        original_verdict="issues", final_verdict="issues",
        output_json="{}", gate_json="{}",
    )
    row = records.latest_trace_for_thread("C3", "t3")
    assert row is not None
    assert row["pr_number"] == 2  # newest
