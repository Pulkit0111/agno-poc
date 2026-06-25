"""Spine tests: the Code Review tools enqueue real work onto the durable queue.
Deterministic (no LLM/network)."""

from __future__ import annotations

import tempfile

import bott.shared.persistence.store as store
from bott.agents.code_review import member
from bott.agents.code_review.member import (
    reset_review_target,
    set_review_target,
    start_rereview,
    start_review,
)
from bott.shared import config


def _fresh_store():
    store.DB_FILE = tempfile.mktemp(suffix=".db")
    store.init_db()


def test_start_review_enqueues_review_task():
    _fresh_store()
    token = set_review_target({"channel": "C1", "thread_ts": "t1", "trigger_ts": "x1"})
    try:
        msg = start_review("https://github.com/octo/repo/pull/42")
    finally:
        reset_review_target(token)

    assert "octo/repo#42" in msg
    task = store.next_pending()
    assert task.kind == "review"
    args = dict(task.args)
    assert args.pop("model_id") == config.bott_model()  # one model everywhere
    assert args == {
        "owner": "octo", "name": "repo", "number": 42,
        "channel": "C1", "thread_ts": "t1", "trigger_ts": "x1",
    }


def test_start_review_with_unparseable_url_does_not_enqueue():
    _fresh_store()
    token = set_review_target({"channel": "C1", "thread_ts": "t1"})
    try:
        msg = start_review("can you look at my code")
    finally:
        reset_review_target(token)

    assert store.next_pending() is None
    assert "PR" in msg or "link" in msg.lower()


def test_start_rereview_enqueues_rereview_task():
    _fresh_store()
    token = set_review_target({"channel": "C1", "thread_ts": "t1", "trigger_ts": "x1"})
    try:
        start_rereview("I fixed the CSRF thing")
    finally:
        reset_review_target(token)

    task = store.next_pending()
    assert task.kind == "rereview"
    assert task.args["reply_text"] == "I fixed the CSRF thing"
    assert task.args["channel"] == "C1"


def test_start_review_without_target_queues_without_channel():
    _fresh_store()
    msg = start_review("https://github.com/octo/repo/pull/42")
    assert "octo/repo#42" in msg
    task = store.next_pending()
    assert task.kind == "review"
    assert task.args["channel"] is None


def test_review_tools_returns_both_callables():
    tools = member.review_tools()
    assert {t.__name__ for t in tools} == {"start_review", "start_rereview"}
