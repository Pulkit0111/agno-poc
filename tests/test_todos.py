"""Tests for the personal todos store: round-trips + per-user isolation.

Same fixture shape as tests/test_action_items.py — fresh SQLite DB per test via
AGENTOS_DB_PATH + db.get_engine(fresh=True) + schema.init_schema().
"""

from __future__ import annotations

import os

import pytest

from bott.shared import db
from bott.shared.persistence import todos as store
from bott.shared.schema import init_schema


@pytest.fixture
def tstore(monkeypatch, tmp_path):
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        monkeypatch.setenv("DATABASE_URL", test_url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "todos_test.db"))
    db.get_engine(fresh=True)
    init_schema()
    yield
    db.get_engine(fresh=True)


# ---------------------------------------------------------------------------
# Round-trips
# ---------------------------------------------------------------------------

def test_add_and_list(tstore):
    tid = store.add("alice", "Write the report")
    assert isinstance(tid, int) and tid > 0
    items = store.list_for("alice")
    assert len(items) == 1
    assert items[0]["id"] == tid
    assert items[0]["text"] == "Write the report"
    assert items[0]["done"] == 0


def test_list_newest_first(tstore):
    store.add("alice", "first")
    store.add("alice", "second")
    items = store.list_for("alice")
    assert [i["text"] for i in items] == ["second", "first"]


def test_set_done_true(tstore):
    tid = store.add("alice", "task")
    ok = store.set_done("alice", tid, True)
    assert ok is True
    items = store.list_for("alice")
    assert items[0]["done"] == 1


def test_set_done_false_untoggles(tstore):
    tid = store.add("alice", "task")
    store.set_done("alice", tid, True)
    ok = store.set_done("alice", tid, False)
    assert ok is True
    items = store.list_for("alice")
    assert items[0]["done"] == 0


def test_delete_removes_row(tstore):
    tid = store.add("alice", "task")
    ok = store.delete("alice", tid)
    assert ok is True
    assert store.list_for("alice") == []


def test_clear_done_removes_only_done(tstore):
    open_id = store.add("alice", "still open")
    done_id = store.add("alice", "finished")
    store.set_done("alice", done_id, True)
    removed = store.clear_done("alice")
    assert removed == 1
    remaining = store.list_for("alice")
    assert [i["id"] for i in remaining] == [open_id]


def test_clear_done_returns_zero_when_none_done(tstore):
    store.add("alice", "still open")
    assert store.clear_done("alice") == 0


# ---------------------------------------------------------------------------
# Isolation: user B cannot see or modify user A's todos
# ---------------------------------------------------------------------------

def test_user_b_cannot_see_user_a_todos(tstore):
    store.add("alice", "Alice's secret todo")
    assert store.list_for("bob") == []


def test_user_b_set_done_returns_false(tstore):
    tid = store.add("alice", "Alice's todo")
    result = store.set_done("bob", tid, True)
    assert result is False
    # Alice's row untouched
    assert store.list_for("alice")[0]["done"] == 0


def test_user_b_delete_returns_false(tstore):
    tid = store.add("alice", "Alice's todo")
    result = store.delete("bob", tid)
    assert result is False
    # Alice's row still there
    assert len(store.list_for("alice")) == 1


def test_user_b_clear_done_does_not_touch_alice(tstore):
    tid = store.add("alice", "Alice's todo")
    store.set_done("alice", tid, True)
    removed = store.clear_done("bob")
    assert removed == 0
    assert len(store.list_for("alice")) == 1
