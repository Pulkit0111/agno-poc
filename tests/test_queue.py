import os
import threading
import time

import pytest
from sqlalchemy import text

from bott.shared import alerts, db
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


def test_recover_orphans_leaves_recently_claimed_jobs_alone(engine):
    """Regression: recover_orphans() used to blanket-fail EVERY 'running' job on any boot —
    under multiple worker instances, restarting instance A would wrongly fail a job
    instance B is legitimately still mid-way through. A job claimed moments ago must be
    left running."""
    jid = queue.enqueue("review", {"pr": 1}, user_id="u")
    queue.claim_one()  # sets status='running', claimed_at=now
    recovered = queue.recover_orphans(stale_after_s=3600)  # 1 hour — nowhere close yet
    assert recovered == 0
    row = queue.job_detail(jid)
    assert row["status"] == "running"


def test_recover_orphans_fails_genuinely_stale_jobs(engine):
    """A job stuck in 'running' well past the staleness window — its claiming instance
    presumably crashed and never came back — must still be recovered."""
    jid = queue.enqueue("review", {"pr": 1}, user_id="u")
    queue.claim_one()
    with db.get_engine().begin() as c:
        c.execute(text("UPDATE jobs SET claimed_at=:t WHERE id=:id"),
                  {"t": time.time() - 7200, "id": jid})  # claimed 2h ago
    recovered = queue.recover_orphans(stale_after_s=1800)  # 30 min window
    assert recovered == 1
    row = queue.job_detail(jid)
    assert row["status"] == "failed"
    assert "interrupted by restart" in row["error"]


def test_recover_orphans_treats_missing_claimed_at_as_immediately_eligible(engine):
    """Legacy rows from before this column existed have no claimed_at — treat those as
    eligible for recovery immediately, matching the old unconditional behavior for them."""
    jid = queue.enqueue("review", {"pr": 1}, user_id="u")
    queue.claim_one()
    with db.get_engine().begin() as c:
        c.execute(text("UPDATE jobs SET claimed_at=NULL WHERE id=:id"), {"id": jid})
    recovered = queue.recover_orphans(stale_after_s=3600)
    assert recovered == 1


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


def _run_worker_once(handler, engine_fixture):
    """Run worker_main until it has drained the queue, then stop it."""
    stop = threading.Event()

    def handler_then_stop(job):
        try:
            handler(job)
        finally:
            stop.set()

    queue.worker_main(handler_then_stop, poll=0.01, stop=stop)


def test_final_failure_alerts_admins(engine, monkeypatch):
    """Regression: a job that exhausts all retries used to fail silently — nobody found out
    except a user noticing their request never got a response."""
    alerted = []
    monkeypatch.setattr(alerts, "alert_admins", lambda text: alerted.append(text))
    jid = queue.enqueue("review", {"pr": 1}, user_id="u")
    # Pre-set attempts to _MAX_ATTEMPTS - 1 so this failure is the LAST allowed attempt.
    with db.get_engine().begin() as c:
        c.execute(text("UPDATE jobs SET attempts=:a WHERE id=:id"),
                  {"a": queue._MAX_ATTEMPTS - 1, "id": jid})

    def failing_handler(job):
        raise RuntimeError("boom")

    _run_worker_once(failing_handler, engine)

    assert alerted and "boom" in alerted[0]
    with db.get_engine().connect() as c:
        row = c.execute(text("SELECT status FROM jobs WHERE id=:id"), {"id": jid}).fetchone()
    assert row[0] == "failed"


def test_retryable_failure_does_not_alert(engine, monkeypatch):
    """A failure that still has retries left must not page anyone — only the FINAL,
    out-of-retries failure is alert-worthy."""
    alerted = []
    monkeypatch.setattr(alerts, "alert_admins", lambda text: alerted.append(text))
    queue.enqueue("review", {"pr": 1}, user_id="u")

    def failing_handler(job):
        raise RuntimeError("transient")

    _run_worker_once(failing_handler, engine)

    assert alerted == []


def test_claim_failure_alerts_and_backs_off_instead_of_crashing(engine, monkeypatch):
    """Regression: an exception from claim_one() itself (e.g. the DB is unreachable) used
    to propagate out of worker_main and kill the whole background-worker thread silently —
    nobody drained the queue again until a restart. It must now be caught, alerted, and
    retried instead of taking the loop down."""
    alerted = []
    monkeypatch.setattr(alerts, "alert_admins_throttled",
                        lambda key, text, **kw: alerted.append((key, text)))

    calls = {"n": 0}
    real_claim_one = queue.claim_one

    def flaky_claim_one():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db unreachable")
        return real_claim_one()

    monkeypatch.setattr(queue, "claim_one", flaky_claim_one)
    stop = threading.Event()

    def stop_after_first_real_poll(job=None):
        stop.set()

    # No job ever gets claimed (queue is empty) — just prove the loop survives the first
    # claim_one() exception and keeps polling instead of the thread dying.
    t = threading.Thread(target=queue.worker_main, args=(lambda job: None,),
                         kwargs={"poll": 0.01, "stop": stop})
    t.start()
    stop.wait(0.2)
    stop.set()
    t.join(timeout=2)

    assert not t.is_alive(), "worker thread must exit cleanly once stop is set"
    assert calls["n"] >= 2, "worker must keep calling claim_one after the first failure"
    assert alerted and alerted[0][0] == "worker-claim-failed"
