"""Code Review specialist — the manager's first team member.

Reviews are slow (clone + LLM), so this agent does NOT run a review inline. Its tools
enqueue work onto the durable worker (the same queue the Slack/webhook paths already
use); the worker runs the pipeline, posts the verdict, and persists the trace. The
agent's job is just to recognize the request, pull out the PR reference, and hand off.

The agent is built ONCE and shared by both front doors (Slack + AgentOS HTTP). Where a
queued review should report back is request-scoped state held in a ``ContextVar``: the
Slack handler sets it around ``team.run(...)``; HTTP/UI runs leave it unset (and so queue
a review with no Slack post-target).
"""

from __future__ import annotations

import contextvars
from typing import Callable, Optional, TypedDict

from agno.run.base import RunContext

from bott.shared.config import bott_model
from bott.shared.persistence import store

from .pr_ref import extract_pr_ref


class ReviewTarget(TypedDict, total=False):
    """Where a queued review should report back. Present for Slack runs, absent for
    UI/HTTP runs (which queue without a Slack post-target)."""

    channel: Optional[str]
    thread_ts: Optional[str]
    trigger_ts: Optional[str]


# Request-scoped Slack target. The Slack handler sets this around team.run(...);
# HTTP/UI runs leave it None.
_review_target: contextvars.ContextVar[Optional[ReviewTarget]] = contextvars.ContextVar(
    "review_target", default=None
)


def set_review_target(target: Optional[ReviewTarget]) -> contextvars.Token:
    return _review_target.set(target)


def reset_review_target(token: contextvars.Token) -> None:
    _review_target.reset(token)


def _resolve_target(run_context: Optional[RunContext]) -> ReviewTarget:
    """Where the review verdict should post. The Agno Slack interface injects the Slack
    channel/thread as run dependencies (Agno injects run_context into tools that ask for
    it); fall back to the contextvar (other trigger paths)."""
    deps = (getattr(run_context, "dependencies", None) or {}) if run_context else {}
    channel = deps.get("Slack channel_id")
    thread = deps.get("Slack thread_ts")
    if channel:
        return {"channel": channel, "thread_ts": thread, "trigger_ts": thread}
    return _review_target.get() or {}


def start_review(pr_url: str, run_context: Optional[RunContext] = None) -> str:
    """Queue a code review of a GitHub pull request.

    Args:
        pr_url: The GitHub PR URL or 'owner/repo#number' reference.
    """
    ref = extract_pr_ref(pr_url)
    if not ref:
        return "I couldn't find a PR reference in that — ask the user for the GitHub PR link."
    owner, repo, number = ref
    target = _resolve_target(run_context)
    store.enqueue(
        "review",
        {
            "owner": owner, "name": repo, "number": number,
            "channel": target.get("channel"), "thread_ts": target.get("thread_ts"),
            "trigger_ts": target.get("trigger_ts"),
            "model_id": bott_model(),
        },
    )
    return f"Queued a review of {owner}/{repo}#{number}."


def start_rereview(reply_text: str = "", run_context: Optional[RunContext] = None) -> str:
    """Queue a re-review (another pass) of the PR already reviewed in this thread.

    Args:
        reply_text: The user's follow-up message, so the next pass has their feedback.
    """
    target = _resolve_target(run_context)
    if not target.get("thread_ts"):
        return "Re-reviews only work in a Slack thread that already has a review."
    store.enqueue(
        "rereview",
        {
            "channel": target.get("channel"), "thread_ts": target.get("thread_ts"),
            "trigger_ts": target.get("trigger_ts"), "reply_text": reply_text,
            "model_id": bott_model(),
        },
    )
    return "Queued another pass."


def review_tools() -> list[Callable]:
    """The enqueue tools as plain callables (Agno wraps them); directly unit-testable."""
    return [start_review, start_rereview]
