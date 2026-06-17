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

from agno.agent import Agent

from bott.shared.persistence import store

from .pr_ref import extract_pr_ref

CODE_REVIEW_ROLE = (
    "Review GitHub pull requests: queue a review when given a PR, or a re-review when "
    "the user follows up on a PR already reviewed in this thread."
)

CODE_REVIEW_INSTRUCTIONS = [
    "You queue PR reviews; you do not write the review yourself — the engine does that.",
    "To review a PR, call start_review with the GitHub PR URL (or 'owner/repo#number') "
    "exactly as the user gave it; the tool parses the reference.",
    "If the user is following up on a PR already reviewed earlier in this thread "
    "(feedback, 'take another look', 'I fixed X'), call start_rereview with their message.",
    "After queuing, reply in one short, warm sentence — the full verdict is posted "
    "separately when the review finishes.",
]


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


def start_review(pr_url: str) -> str:
    """Queue a code review of a GitHub pull request.

    Args:
        pr_url: The GitHub PR URL or 'owner/repo#number' reference.
    """
    ref = extract_pr_ref(pr_url)
    if not ref:
        return "I couldn't find a PR reference in that — ask the user for the GitHub PR link."
    owner, repo, number = ref
    target = _review_target.get() or {}
    store.enqueue(
        "review",
        {
            "owner": owner, "name": repo, "number": number,
            "channel": target.get("channel"), "thread_ts": target.get("thread_ts"),
            "trigger_ts": target.get("trigger_ts"),
        },
    )
    return f"Queued a review of {owner}/{repo}#{number}."


def start_rereview(reply_text: str = "") -> str:
    """Queue a re-review (another pass) of the PR already reviewed in this thread.

    Args:
        reply_text: The user's follow-up message, so the next pass has their feedback.
    """
    target = _review_target.get() or {}
    if not target.get("thread_ts"):
        return "Re-reviews only work in a Slack thread that already has a review."
    store.enqueue(
        "rereview",
        {
            "channel": target.get("channel"), "thread_ts": target.get("thread_ts"),
            "trigger_ts": target.get("trigger_ts"), "reply_text": reply_text,
        },
    )
    return "Queued another pass."


def review_tools() -> list[Callable]:
    """The enqueue tools as plain callables (Agno wraps them); directly unit-testable."""
    return [start_review, start_rereview]


def build_code_review_agent(model=None) -> Agent:
    """The Code Review member. `model=None` lets it inherit the manager Team's model."""
    return Agent(
        id="code-review",
        name="Code Review Agent",
        role=CODE_REVIEW_ROLE,
        model=model,
        tools=review_tools(),
        instructions=CODE_REVIEW_INSTRUCTIONS,
        telemetry=False,
    )
