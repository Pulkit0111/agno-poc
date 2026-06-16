"""The manager — an Agno Team leader that talks like a teammate and delegates.

This is the conversational front door (Slack). The leader holds Bott's personality,
chats directly for anything that isn't a task, and delegates real work to specialist
members. Today there is one member (Code Review); agents 2..N drop in as additional
members with distinct roles, no change to this routing layer.
"""

from __future__ import annotations

from agno.team import Team, TeamMode

from bott.agents.code_review.member import SlackContext, build_code_review_agent
from bott.shared.config import manager_api_key, manager_base_url, manager_model
from bott.shared.model import build_model

from .personality import IDENTITY, NAME, VOICE

# Routing rules only — the voice/persona lives in personality.py (single source of truth).
ROUTING_INSTRUCTIONS = [
    "Your team can review GitHub pull requests. When someone wants a PR reviewed, or "
    "follows up on a PR already reviewed in this thread, delegate to the Code Review Agent "
    "and pass the PR link or reference along verbatim.",
    "For anything else — greetings, questions about what you do, small talk, questions "
    "about an earlier review — answer yourself; don't delegate.",
]


def build_manager(ctx: SlackContext, model_id: str | None = None) -> Team:
    """Build the manager Team for one Slack message. The member inherits this model;
    the leader's voice comes entirely from personality.VOICE. Uses the (fast) MANAGER_MODEL
    — the heavy review runs separately on REVIEW_MODEL in the worker."""
    model = build_model(
        model_id or manager_model(),
        base_url=manager_base_url(),
        api_key=manager_api_key(),
    )
    return Team(
        name=NAME,
        model=model,
        members=[build_code_review_agent(ctx)],
        mode=TeamMode.coordinate,
        description=IDENTITY,
        instructions=[VOICE, *ROUTING_INSTRUCTIONS],
        telemetry=False,
        markdown=False,
    )


def run_manager(team: Team, text: str) -> str:
    """Run the manager on a user message and return its conversational reply."""
    out = team.run(text)
    return (out.content or "").strip()


def stream_manager(team: Team, text: str):
    """Yield the manager's reply as incremental text chunks (for live Slack streaming).
    Only the leader's content deltas are yielded — tool/member events are skipped."""
    for event in team.run(text, stream=True):
        if event.__class__.__name__ != "RunContentEvent":
            continue
        chunk = getattr(event, "content", None)
        if isinstance(chunk, str) and chunk:
            yield chunk
