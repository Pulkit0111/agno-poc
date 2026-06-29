"""Spine tests: the Code Review tools enqueue real work onto the durable Postgres queue.
Deterministic (no LLM/network). Rewrote against queue (dict-shaped jobs) after store.py
was retired in Phase-2-1B."""

from __future__ import annotations

import pytest

from bott.agents.code_review import member
from bott.agents.code_review.member import (
    reset_review_target,
    set_review_target,
    start_rereview,
    start_review,
)
from bott.shared import config, db
from bott.shared.persistence import queue


@pytest.fixture(autouse=True)
def fresh_queue(tmp_path, monkeypatch):
    """Each test gets an isolated SQLite DB for the queue."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "q.db"))
    db.get_engine(fresh=True)
    queue.init_queue()
    yield
    db.get_engine(fresh=True)  # reset engine so next test gets a clean one


def test_start_review_enqueues_review_task():
    token = set_review_target({"channel": "C1", "thread_ts": "t1", "trigger_ts": "x1"})
    try:
        msg = start_review("https://github.com/octo/repo/pull/42")
    finally:
        reset_review_target(token)

    assert "octo/repo#42" in msg
    job = queue.claim_one()
    assert job is not None
    assert job["kind"] == "review"
    args = dict(job["args"])
    assert args.pop("model_id") == config.bott_model()  # one model everywhere
    assert args == {
        "owner": "octo", "name": "repo", "number": 42,
        "channel": "C1", "thread_ts": "t1", "trigger_ts": "x1",
    }
    # user_id must be present (defaults to system when no run_context user)
    assert job["user_id"] == "system@axelerant.com"


def test_start_review_with_unparseable_url_does_not_enqueue():
    token = set_review_target({"channel": "C1", "thread_ts": "t1"})
    try:
        msg = start_review("can you look at my code")
    finally:
        reset_review_target(token)

    assert queue.claim_one() is None
    assert "PR" in msg or "link" in msg.lower()


def test_start_rereview_enqueues_rereview_task():
    token = set_review_target({"channel": "C1", "thread_ts": "t1", "trigger_ts": "x1"})
    try:
        start_rereview("I fixed the CSRF thing")
    finally:
        reset_review_target(token)

    job = queue.claim_one()
    assert job is not None
    assert job["kind"] == "rereview"
    assert job["args"]["reply_text"] == "I fixed the CSRF thing"
    assert job["args"]["channel"] == "C1"
    assert job["user_id"] == "system@axelerant.com"


def test_start_review_carries_run_context_user_id():
    """Human-triggered reviews must carry the caller's user_id (not the system fallback),
    so the queued job is attributed to the person who asked — the isolation-relevant path."""
    from types import SimpleNamespace

    token = set_review_target({"channel": "C1", "thread_ts": "t1", "trigger_ts": "x1"})
    try:
        start_review(
            "https://github.com/octo/repo/pull/42",
            run_context=SimpleNamespace(user_id="alice@axelerant.com", dependencies={}),
        )
    finally:
        reset_review_target(token)

    job = queue.claim_one()
    assert job is not None
    assert job["user_id"] == "alice@axelerant.com"  # caller's id, not system


def test_start_review_without_target_queues_without_channel():
    msg = start_review("https://github.com/octo/repo/pull/42")
    assert "octo/repo#42" in msg
    job = queue.claim_one()
    assert job is not None
    assert job["kind"] == "review"
    assert job["args"]["channel"] is None


def test_review_tools_returns_both_callables():
    tools = member.review_tools()
    assert {t.__name__ for t in tools} == {"start_review", "start_rereview"}
