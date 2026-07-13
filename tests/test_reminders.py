"""Reminder sweep: every due snoozed item gets DMed exactly once, then flipped back to
open so it can never fire twice. Follows the AGENTOS_DB_PATH + init_schema() fixture
pattern used across tests/test_action_items.py and tests/test_queue.py.
"""

from __future__ import annotations

import os
import time

import pytest

from bott.shared import db, reminders
from bott.shared.persistence import action_items as store
from bott.shared.schema import init_schema


@pytest.fixture
def engine(monkeypatch, tmp_path):
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        monkeypatch.setenv("DATABASE_URL", test_url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "reminders.db"))
    db.get_engine(fresh=True)
    init_schema()
    yield
    db.get_engine(fresh=True)


# ---------------------------------------------------------------------------
# sweep_once: DMs exactly the due items, flips them back to open, never twice
# ---------------------------------------------------------------------------

def test_sweep_once_dms_exactly_due_items(engine):
    iid1 = store.add_item("alice", "Renew SSL cert", 1000.0)
    store.snooze_item("alice", iid1, 500.0, 1000.0)  # due
    iid2 = store.add_item("bob", "Ping client", 1000.0)
    store.snooze_item("bob", iid2, 9999.0, 1000.0)  # not due

    sent_calls = []

    def fake_send(user_id, text):
        sent_calls.append((user_id, text))

    count = reminders.sweep_once(1100.0, fake_send)
    assert count == 1
    assert sent_calls == [("alice", "⏰ Snoozed action item is due: Renew SSL cert")]


def test_sweep_once_returns_zero_when_nothing_due(engine):
    assert reminders.sweep_once(time.time(), lambda u, t: None) == 0


def test_sweep_once_marks_reminded_so_status_is_open_again(engine):
    iid = store.add_item("alice", "Task", 1000.0)
    store.snooze_item("alice", iid, 500.0, 1000.0)
    reminders.sweep_once(1100.0, lambda u, t: None)
    items = store.list_items("alice")
    assert items[0]["status"] == "open"
    assert items[0]["remind_at"] is None


def test_sweep_once_is_idempotent_on_rerun(engine):
    iid = store.add_item("alice", "Task", 1000.0)
    store.snooze_item("alice", iid, 500.0, 1000.0)
    calls = []

    def fake_send(u, t):
        calls.append((u, t))

    first = reminders.sweep_once(1100.0, fake_send)
    second = reminders.sweep_once(1100.0, fake_send)
    assert first == 1
    assert second == 0
    assert len(calls) == 1


def test_sweep_once_continues_after_one_dm_failure(engine):
    iid1 = store.add_item("alice", "A", 1000.0)
    store.snooze_item("alice", iid1, 500.0, 1000.0)
    iid2 = store.add_item("bob", "B", 1000.0)
    store.snooze_item("bob", iid2, 500.0, 1000.0)

    def flaky_send(user_id, text):
        if user_id == "alice":
            raise RuntimeError("slack down")

    count = reminders.sweep_once(1100.0, flaky_send)
    assert count == 1  # bob got reminded even though alice's DM raised
    # alice's item was claimed (atomic flip) but the DM failed, so it's RE-snoozed with a
    # short retry delay — never silently marked reminded when it wasn't delivered, and
    # never lost either.
    alice_items = store.list_items("alice")
    assert alice_items[0]["status"] == "snoozed"
    assert alice_items[0]["remind_at"] == 1100.0 + reminders._RETRY_DELAY_S
    # retried (and delivered) on a later sweep once the retry delay has passed
    delivered = []
    assert reminders.sweep_once(1100.0 + reminders._RETRY_DELAY_S,
                                lambda u, t: delivered.append(u)) == 1
    assert delivered == ["alice"]


# ---------------------------------------------------------------------------
# start_reminder_thread / stop_reminder_thread: daemon loop, quiet no-op guard
# ---------------------------------------------------------------------------

def test_start_reminder_thread_noop_quietly_when_slack_not_configured(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    t = reminders.start_reminder_thread(poll=0.01)
    try:
        time.sleep(0.05)
        assert t.is_alive()  # must not have crashed out
    finally:
        reminders.stop_reminder_thread()
        t.join(timeout=2)
    assert not t.is_alive()


def test_start_reminder_thread_sweeps_due_items(engine, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    iid = store.add_item("alice", "Task", 1000.0)
    store.snooze_item("alice", iid, 500.0, 1000.0)

    sent = []
    monkeypatch.setattr(reminders, "_send_dm_via_slack", lambda email, text: sent.append((email, text)))

    t = reminders.start_reminder_thread(poll=0.01)
    try:
        for _ in range(50):
            if sent:
                break
            time.sleep(0.02)
    finally:
        reminders.stop_reminder_thread()
        t.join(timeout=2)
    assert sent == [("alice", "⏰ Snoozed action item is due: Task")]
