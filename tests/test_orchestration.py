"""Spine tests: the Code Review member's tools enqueue real work, and the manager
Team is wired with the right member + mode. These are deterministic (no LLM/network):
the leader's routing is LLM-driven and exercised manually, not in CI."""

from __future__ import annotations

import tempfile

import pr_reviewer.persistence.store as store
from pr_reviewer.orchestration.code_review_agent import SlackContext, make_review_tools


def _fresh_store():
    store.DB_FILE = tempfile.mktemp(suffix=".db")
    store.init_db()


def test_start_review_enqueues_review_task():
    _fresh_store()
    ctx = SlackContext(channel="C1", thread_ts="t1", trigger_ts="x1")
    start_review, _ = make_review_tools(ctx)

    msg = start_review("https://github.com/octo/repo/pull/42")

    assert "octo/repo#42" in msg
    assert ctx.enqueued is True
    task = store.next_pending()
    assert task.kind == "review"
    assert task.args == {
        "owner": "octo", "name": "repo", "number": 42,
        "channel": "C1", "thread_ts": "t1", "trigger_ts": "x1",
    }


def test_start_review_with_unparseable_url_does_not_enqueue():
    _fresh_store()
    ctx = SlackContext(channel="C1", thread_ts="t1")
    start_review, _ = make_review_tools(ctx)

    msg = start_review("can you look at my code")

    assert ctx.enqueued is False
    assert store.next_pending() is None
    assert "PR" in msg or "link" in msg.lower()


def test_start_rereview_enqueues_rereview_task():
    _fresh_store()
    ctx = SlackContext(channel="C1", thread_ts="t1", trigger_ts="x1")
    _, start_rereview = make_review_tools(ctx)

    start_rereview("I fixed the CSRF thing")

    assert ctx.enqueued is True
    task = store.next_pending()
    assert task.kind == "rereview"
    assert task.args["reply_text"] == "I fixed the CSRF thing"
    assert task.args["channel"] == "C1"


def test_manager_team_has_code_review_member_in_coordinate_mode():
    from agno.team import TeamMode

    from pr_reviewer.orchestration.manager import build_manager

    team = build_manager(SlackContext(channel=None, thread_ts=None))

    member_names = [m.name for m in team.members]
    assert "Code Review Agent" in member_names
    assert team.mode == TeamMode.coordinate
