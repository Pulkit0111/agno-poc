import os

import pytest
from sqlalchemy import text

from bott.shared import db
from bott.shared.persistence import queue


@pytest.fixture
def engine(monkeypatch, tmp_path):
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        monkeypatch.setenv("DATABASE_URL", url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "q.db"))
    db.get_engine(fresh=True)
    queue.init_queue()
    # Start every test with an empty queue. SQLite gets a fresh tmp file per test, but a
    # Postgres TEST_DATABASE_URL is shared across tests — without this, a prior test's
    # uncompleted job leaks in (e.g. the dedup test's pending row) and breaks the count.
    with db.get_engine().begin() as c:
        c.execute(text("DELETE FROM jobs"))
    yield


def test_enqueue_claim_complete_round_trip(engine):
    jid = queue.enqueue("review", {"pr": 1}, user_id="alice@x.com")
    claimed = queue.claim_one()
    assert claimed["id"] == jid
    assert claimed["args"] == {"pr": 1}
    assert claimed["user_id"] == "alice@x.com"
    queue.complete(jid)
    assert queue.claim_one() is None  # nothing left pending


def test_dedup_coalesces(engine):
    a = queue.enqueue("review", {"pr": 7}, user_id="u", dedup_key="review:7")
    b = queue.enqueue("review", {"pr": 7}, user_id="u", dedup_key="review:7")
    assert a == b  # same pending job reused


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs Postgres")
def test_skip_locked_each_job_once(engine):
    ids = {queue.enqueue("k", {"n": n}, user_id="u") for n in range(20)}
    seen = []
    while True:
        c = queue.claim_one()
        if c is None:
            break
        seen.append(c["id"])
        queue.complete(c["id"])
    assert sorted(seen) == sorted(ids)  # exactly once
