"""Tests for the review_trends skill and trace_stats aggregate helper.

Uses an in-memory SQLite fixture (same pattern as test_records.py).
Verifies:
  - trace_stats returns correct totals / by_verdict / by_repo / rereview_changed
  - review_trends() output contains the verdict counts and the descriptive-only disclaimer
  - review_trends() handles the empty-DB case gracefully
  - review_trends_tools() returns the registered tool callable
"""

from __future__ import annotations

import os
import time

import pytest

from bott.shared import db
from bott.shared.persistence import records
from bott.shared.schema import init_schema
from bott.skills.review_trends import review_trends_impl, review_trends_tools

# ---------------------------------------------------------------------------
# Shared fixture — isolated SQLite DB
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(monkeypatch, tmp_path):
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        monkeypatch.setenv("DATABASE_URL", test_url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "trends_test.db"))
    db.get_engine(fresh=True)
    init_schema()
    yield
    db.get_engine(fresh=True)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _save(owner, name, final_verdict, original_verdict=None, offset_secs=0):
    """Save a trace with a controllable created timestamp."""
    records.save_trace(
        channel="C1",
        thread_ts=f"ts-{owner}-{name}-{final_verdict}-{offset_secs}",
        owner=owner,
        name=name,
        pr_number=1,
        original_verdict=original_verdict,
        final_verdict=final_verdict,
        output_json="{}",
        gate_json="{}",
    )


# ---------------------------------------------------------------------------
# trace_stats — unit tests
# ---------------------------------------------------------------------------

def test_trace_stats_empty(store):
    stats = records.trace_stats()
    assert stats["total"] == 0
    assert stats["by_verdict"] == {}
    assert stats["by_repo"] == []
    assert stats["rereview_changed"] == 0
    assert stats["by_week"] == {}


def test_trace_stats_total(store):
    _save("org", "repo-a", "approve")
    _save("org", "repo-a", "issues")
    _save("org", "repo-b", "suggestions")
    stats = records.trace_stats()
    assert stats["total"] == 3


def test_trace_stats_by_verdict(store):
    _save("org", "r", "approve")
    _save("org", "r", "approve")
    _save("org", "r", "issues")
    stats = records.trace_stats()
    assert stats["by_verdict"]["approve"] == 2
    assert stats["by_verdict"]["issues"] == 1


def test_trace_stats_by_repo(store):
    _save("axe", "alpha", "approve")
    _save("axe", "alpha", "approve")
    _save("axe", "beta", "issues")
    stats = records.trace_stats()
    # by_repo is a list of (repo_str, count) sorted descending
    repos = dict(stats["by_repo"])
    assert repos["axe/alpha"] == 2
    assert repos["axe/beta"] == 1
    # alpha should come first (higher count)
    assert stats["by_repo"][0][0] == "axe/alpha"


def test_trace_stats_rereview_changed(store):
    # original == final  → should NOT count
    _save("org", "r", "approve", original_verdict="approve")
    # original != final  → SHOULD count
    _save("org", "r", "issues", original_verdict="approve")
    # no original (first review) → should NOT count
    _save("org", "r", "suggestions", original_verdict=None)
    stats = records.trace_stats()
    assert stats["rereview_changed"] == 1


def test_trace_stats_since_epoch_filters(store):
    now = time.time()
    # Save one trace at roughly "now"; it will have created ~ now
    _save("org", "r", "approve")
    # Query with a future since_epoch should exclude it
    stats_future = records.trace_stats(since_epoch=now + 3600)
    assert stats_future["total"] == 0
    # Query with a past since_epoch should include it
    stats_past = records.trace_stats(since_epoch=now - 3600)
    assert stats_past["total"] == 1


def test_trace_stats_by_week_populated(store):
    _save("org", "r", "approve")
    stats = records.trace_stats()
    # There should be exactly one week bucket
    assert len(stats["by_week"]) == 1
    week_key = next(iter(stats["by_week"]))
    # Key should look like "YYYY-Www" (e.g. "2026-W27")
    assert "-W" in week_key
    assert stats["by_week"][week_key] == 1


# ---------------------------------------------------------------------------
# review_trends_impl — integration/formatting tests
# ---------------------------------------------------------------------------

_DISCLAIMER_FRAGMENT = "descriptive counts"


def test_review_trends_empty_db_message(store):
    result = review_trends_impl(days=30)
    assert "No review traces" in result
    assert _DISCLAIMER_FRAGMENT in result


def test_review_trends_includes_disclaimer(store):
    _save("org", "r", "approve")
    result = review_trends_impl(days=30)
    assert _DISCLAIMER_FRAGMENT in result


def test_review_trends_shows_verdict_counts(store):
    _save("org", "r", "approve")
    _save("org", "r", "approve")
    _save("org", "r", "issues")
    result = review_trends_impl(days=30)
    assert "approve" in result
    assert "issues" in result
    # The count "2" for approve and "1" for issues should appear
    assert "2" in result
    assert "1" in result


def test_review_trends_shows_rereview_changed(store):
    _save("org", "r", "issues", original_verdict="approve")
    result = review_trends_impl(days=30)
    assert "Re-review" in result or "re-review" in result.lower()


def test_review_trends_days_window(store):
    # A trace saved now should appear in a 30-day window
    _save("org", "r", "approve")
    result_30 = review_trends_impl(days=30)
    assert "Total reviews: 1" in result_30

    # A very narrow window (0 days → since = now, so the just-saved trace is excluded)
    result_0 = review_trends_impl(days=0)
    assert "No review traces" in result_0


def test_review_trends_shows_top_repos(store):
    _save("axe", "project-x", "approve")
    _save("axe", "project-x", "issues")
    _save("axe", "project-y", "suggestions")
    result = review_trends_impl(days=30)
    assert "axe/project-x" in result


# ---------------------------------------------------------------------------
# review_trends_tools — wiring smoke-test
# ---------------------------------------------------------------------------

def test_review_trends_tools_returns_list(store):
    tools = review_trends_tools()
    assert isinstance(tools, list)
    assert len(tools) == 1


def test_review_trends_tools_has_name(store):
    tools = review_trends_tools()
    tool_fn = tools[0]
    name = getattr(tool_fn, "name", None) or getattr(tool_fn, "__name__", None)
    assert name == "review_trends"
