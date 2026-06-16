"""Code Review specialist — the manager's first team member.

Reviews are slow (clone + LLM), so this agent does NOT run a review inline. Its tools
enqueue work onto the durable worker (the same queue the Slack/webhook paths already
use); the worker runs the pipeline, posts the verdict, and persists the trace. The
agent's job is just to recognize the request, pull out the PR reference, and hand off.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

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


@dataclass
class SlackContext:
    """Per-message Slack context the tools need to enqueue a routable task. Mutable:
    a tool sets `enqueued=True` so the Slack layer knows to add the 'eyes' reaction."""

    channel: Optional[str]
    thread_ts: Optional[str]
    trigger_ts: Optional[str] = None
    enqueued: bool = False


def make_review_tools(ctx: SlackContext) -> list[Callable]:
    """Build the enqueue tools bound to one Slack context. Returned as plain callables
    (Agno wraps them as tools) so they're directly unit-testable."""

    def start_review(pr_url: str) -> str:
        """Queue a code review of a GitHub pull request.

        Args:
            pr_url: The GitHub PR URL or 'owner/repo#number' reference.
        """
        ref = extract_pr_ref(pr_url)
        if not ref:
            return "I couldn't find a PR reference in that — ask the user for the GitHub PR link."
        owner, repo, number = ref
        store.enqueue(
            "review",
            {
                "owner": owner, "name": repo, "number": number,
                "channel": ctx.channel, "thread_ts": ctx.thread_ts,
                "trigger_ts": ctx.trigger_ts,
            },
        )
        ctx.enqueued = True
        return f"Queued a review of {owner}/{repo}#{number}."

    def start_rereview(reply_text: str = "") -> str:
        """Queue a re-review (another pass) of the PR already reviewed in this thread.

        Args:
            reply_text: The user's follow-up message, so the next pass has their feedback.
        """
        store.enqueue(
            "rereview",
            {
                "channel": ctx.channel, "thread_ts": ctx.thread_ts,
                "trigger_ts": ctx.trigger_ts, "reply_text": reply_text,
            },
        )
        ctx.enqueued = True
        return "Queued another pass."

    return [start_review, start_rereview]


def build_code_review_agent(ctx: SlackContext, model=None) -> Agent:
    """The Code Review member. `model=None` lets it inherit the manager Team's model."""
    return Agent(
        name="Code Review Agent",
        role=CODE_REVIEW_ROLE,
        model=model,
        tools=make_review_tools(ctx),
        instructions=CODE_REVIEW_INSTRUCTIONS,
        telemetry=False,
    )
