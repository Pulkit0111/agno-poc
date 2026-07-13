"""Tests for personal action-items: store round-trips, isolation, and tool behavior.

Uses the same SQLite test-engine pattern as test_records.py:
  AGENTOS_DB_PATH + db.get_engine(fresh=True) + schema.init_schema()
Tool tests use SimpleNamespace(user_id=...) as run_context (like test_scheduling_tools.py).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import bott.skills.action_items as ai_skills
from bott.shared import db
from bott.shared.persistence import action_items as store
from bott.shared.schema import init_schema

# ---------------------------------------------------------------------------
# Shared fixture — fresh SQLite DB per test
# ---------------------------------------------------------------------------

@pytest.fixture
def astore(monkeypatch, tmp_path):
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        monkeypatch.setenv("DATABASE_URL", test_url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "ai_test.db"))
    db.get_engine(fresh=True)
    init_schema()
    yield
    db.get_engine(fresh=True)  # reset so later tests start clean


# ---------------------------------------------------------------------------
# Store round-trips
# ---------------------------------------------------------------------------

def test_add_and_list(astore):
    item_id = store.add_item("alice", "Write the report", 1000.0)
    assert isinstance(item_id, int) and item_id > 0
    items = store.list_items("alice")
    assert len(items) == 1
    assert items[0]["text"] == "Write the report"
    assert items[0]["status"] == "open"
    assert items[0]["id"] == item_id


def test_list_newest_first(astore):
    store.add_item("alice", "first", 1000.0)
    store.add_item("alice", "second", 1001.0)
    items = store.list_items("alice")
    assert items[0]["text"] == "second"
    assert items[1]["text"] == "first"


def test_complete_hides_from_default_list(astore):
    iid = store.add_item("alice", "Do something", 1000.0)
    ok = store.complete_item("alice", iid, 1001.0)
    assert ok is True
    items = store.list_items("alice")
    assert len(items) == 0


def test_complete_appears_in_include_done(astore):
    iid = store.add_item("alice", "Done thing", 1000.0)
    store.complete_item("alice", iid, 1001.0)
    items = store.list_items("alice", include_done=True)
    assert any(it["id"] == iid and it["status"] == "done" for it in items)


def test_snooze_sets_status_and_remind_at(astore):
    iid = store.add_item("alice", "Snooze me", 1000.0)
    ok = store.snooze_item("alice", iid, 9999.0, 1001.0)
    assert ok is True
    items = store.list_items("alice")  # snoozed is NOT done, so appears in default list
    assert len(items) == 1
    assert items[0]["status"] == "snoozed"
    assert items[0]["remind_at"] == 9999.0


def test_due_reminders_returns_past_items(astore):
    iid = store.add_item("alice", "Remind me", 1000.0)
    store.snooze_item("alice", iid, 500.0, 1001.0)  # remind_at=500, already past now=1100
    due = store.due_reminders(1100.0)
    assert any(it["id"] == iid for it in due)


def test_due_reminders_excludes_future(astore):
    iid = store.add_item("alice", "Future snooze", 1000.0)
    store.snooze_item("alice", iid, 9999.0, 1001.0)  # not due yet
    due = store.due_reminders(1100.0)
    assert not any(it["id"] == iid for it in due)


# ---------------------------------------------------------------------------
# source column: default "user", explicit override, surfaced in list/due_reminders
# ---------------------------------------------------------------------------

def test_add_item_default_source_is_user(astore):
    iid = store.add_item("alice", "task", 1000.0)
    items = store.list_items("alice")
    assert items[0]["id"] == iid
    assert items[0]["source"] == "user"


def test_add_item_explicit_source(astore):
    store.add_item("alice", "console-created", 1000.0, source="console")
    items = store.list_items("alice")
    assert items[0]["source"] == "console"


def test_due_reminders_includes_source(astore):
    iid = store.add_item("alice", "task", 1000.0, source="dsm")
    store.snooze_item("alice", iid, 500.0, 1001.0)
    due = store.due_reminders(1100.0)
    assert due[0]["source"] == "dsm"


# ---------------------------------------------------------------------------
# mark_reminded: flips a snoozed item back to open, clears remind_at
# ---------------------------------------------------------------------------

def test_mark_reminded_resets_status_and_clears_remind_at(astore):
    iid = store.add_item("alice", "task", 1000.0)
    store.snooze_item("alice", iid, 500.0, 1001.0)
    store.mark_reminded(iid)
    items = store.list_items("alice")
    assert items[0]["status"] == "open"
    assert items[0]["remind_at"] is None


def test_mark_reminded_no_longer_due(astore):
    iid = store.add_item("alice", "task", 1000.0)
    store.snooze_item("alice", iid, 500.0, 1001.0)
    store.mark_reminded(iid)
    assert store.due_reminders(2000.0) == []


# ---------------------------------------------------------------------------
# has_item_with_text: dedup helper for idempotent auto-capture (e.g. DSM blockers)
# ---------------------------------------------------------------------------

def test_has_item_with_text_true_after_add(astore):
    store.add_item("alice", "Follow up on your blocker: infra", 1000.0, source="dsm")
    assert store.has_item_with_text("alice", "Follow up on your blocker: infra", "dsm") is True


def test_has_item_with_text_false_for_other_user(astore):
    store.add_item("alice", "Follow up on your blocker: infra", 1000.0, source="dsm")
    assert store.has_item_with_text("bob", "Follow up on your blocker: infra", "dsm") is False


def test_has_item_with_text_false_for_other_source(astore):
    store.add_item("alice", "Follow up on your blocker: infra", 1000.0, source="user")
    assert store.has_item_with_text("alice", "Follow up on your blocker: infra", "dsm") is False


# ---------------------------------------------------------------------------
# Isolation: user B cannot see or modify user A's items
# ---------------------------------------------------------------------------

def test_user_b_cannot_see_user_a_items(astore):
    store.add_item("alice", "Alice's secret item", 1000.0)
    bob_items = store.list_items("bob")
    assert len(bob_items) == 0


def test_user_b_complete_returns_false(astore):
    iid = store.add_item("alice", "Alice's item", 1000.0)
    result = store.complete_item("bob", iid, 1001.0)
    assert result is False


def test_user_b_complete_leaves_a_item_unchanged(astore):
    iid = store.add_item("alice", "Alice's item", 1000.0)
    store.complete_item("bob", iid, 1001.0)  # Bob attempts; should be a no-op
    alice_items = store.list_items("alice")
    assert len(alice_items) == 1
    assert alice_items[0]["status"] == "open"


def test_user_b_snooze_returns_false(astore):
    iid = store.add_item("alice", "Alice's item", 1000.0)
    result = store.snooze_item("bob", iid, 9999.0, 1001.0)
    assert result is False


def test_user_b_snooze_leaves_a_item_unchanged(astore):
    iid = store.add_item("alice", "Alice's item", 1000.0)
    store.snooze_item("bob", iid, 9999.0, 1001.0)  # Bob attempts; should be a no-op
    alice_items = store.list_items("alice")
    assert len(alice_items) == 1
    assert alice_items[0]["status"] == "open"
    assert alice_items[0]["remind_at"] is None


# ---------------------------------------------------------------------------
# Tool-level tests (via _impl functions + SimpleNamespace run_context)
# ---------------------------------------------------------------------------

def test_add_action_item_tool(astore):
    ctx = SimpleNamespace(user_id="alice")
    out = ai_skills._add_action_item_impl(ctx, "Follow up with client")
    assert "Added action item" in out
    assert "Follow up with client" in out


def test_add_action_item_tool_sets_source_user(astore):
    ctx = SimpleNamespace(user_id="alice")
    ai_skills._add_action_item_impl(ctx, "Follow up with client")
    items = store.list_items("alice")
    assert items[0]["source"] == "user"


def test_add_action_item_blank_user_fails_closed(astore):
    ctx = SimpleNamespace(user_id=None)
    out = ai_skills._add_action_item_impl(ctx, "Should not be saved")
    assert "couldn't tell who you are" in out.lower()
    # Nothing written — list for any user is empty
    assert store.list_items("nobody") == []


def test_add_action_item_empty_string_user_fails_closed(astore):
    ctx = SimpleNamespace(user_id="  ")
    out = ai_skills._add_action_item_impl(ctx, "Should not be saved")
    assert "couldn't tell who you are" in out.lower()


def test_complete_action_item_tool(astore):
    iid = store.add_item("alice", "Task to complete", 1000.0)
    ctx = SimpleNamespace(user_id="alice")
    out = ai_skills._complete_action_item_impl(ctx, iid)
    assert "done" in out.lower()


def test_complete_action_item_blank_user_fails_closed(astore):
    iid = store.add_item("alice", "Task", 1000.0)
    ctx = SimpleNamespace(user_id=None)
    out = ai_skills._complete_action_item_impl(ctx, iid)
    assert "couldn't tell who you are" in out.lower()
    # Alice's item should remain open
    items = store.list_items("alice")
    assert len(items) == 1 and items[0]["status"] == "open"


def test_snooze_action_item_tool_valid_iso(astore):
    iid = store.add_item("alice", "Snooze me", 1000.0)
    ctx = SimpleNamespace(user_id="alice")
    out = ai_skills._snooze_action_item_impl(ctx, iid, "2030-01-01T09:00:00")
    assert "snoozed" in out.lower()


def test_snooze_action_item_tool_bad_date(astore):
    iid = store.add_item("alice", "Snooze me", 1000.0)
    ctx = SimpleNamespace(user_id="alice")
    out = ai_skills._snooze_action_item_impl(ctx, iid, "next thursday")
    assert "couldn't parse" in out.lower()


def test_list_my_action_items_tool(astore):
    store.add_item("alice", "Item A", 1000.0)
    store.add_item("alice", "Item B", 1001.0)
    ctx = SimpleNamespace(user_id="alice")
    out = ai_skills._list_my_action_items_impl(ctx)
    assert "Item A" in out
    assert "Item B" in out


def test_list_my_action_items_tool_empty(astore):
    ctx = SimpleNamespace(user_id="alice")
    out = ai_skills._list_my_action_items_impl(ctx)
    assert "no open action items" in out.lower()


# ---------------------------------------------------------------------------
# action_items_tools() returns exactly 4 tools
# ---------------------------------------------------------------------------

def test_action_items_tools_returns_four():
    tools = ai_skills.action_items_tools()
    assert len(tools) == 4
    names = {getattr(t, "name", None) or getattr(t, "__name__", None) for t in tools}
    assert "add_action_item" in names
    assert "list_my_action_items" in names
    assert "complete_action_item" in names
    assert "snooze_action_item" in names
