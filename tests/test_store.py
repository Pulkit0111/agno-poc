import tempfile

import pytest

import bott.shared.persistence.store as store


@pytest.fixture()
def temp_db():
    old = store.DB_FILE
    store.DB_FILE = tempfile.mktemp(suffix=".db")
    store.init_db()
    yield store.DB_FILE
    store.DB_FILE = old


def test_enqueue_next_done(temp_db):
    tid = store.enqueue("review", {"owner": "o", "name": "r", "number": 1})
    t = store.next_pending()
    assert t and t.id == tid and t.kind == "review" and t.attempts == 0
    assert store.next_pending() is None  # now running, not pending
    store.mark_done(tid)


def test_requeue_increments_attempts(temp_db):
    tid = store.enqueue("review", {})
    store.next_pending()
    store.requeue(tid)
    t = store.next_pending()
    assert t.attempts == 1


def test_recover_orphans(temp_db):
    store.enqueue("review", {})
    store.next_pending()  # -> running
    assert store.recover_orphans() == 1
    assert store.next_pending() is None  # orphan marked failed, not re-run
