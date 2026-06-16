"""The manager — an Agno Team leader that talks like a teammate and delegates.

This is the conversational front door (Slack). The leader holds Bott's personality,
chats directly for anything that isn't a task, and delegates real work to specialist
members. Today there is one member (Code Review); agents 2..N drop in as additional
members with distinct roles, no change to this routing layer.
"""

from __future__ import annotations

from agno.models.openai import OpenAIChat
from agno.team import Team, TeamMode

from bott.agents.code_review.member import SlackContext, build_code_review_agent
from bott.shared.config import DEFAULT_MODEL

from .personality import IDENTITY, NAME, VOICE

# Routing rules only — the voice/persona lives in personality.py (single source of truth).
ROUTING_INSTRUCTIONS = [
    "Your team can review GitHub pull requests. When someone wants a PR reviewed, or "
    "follows up on a PR already reviewed in this thread, delegate to the Code Review Agent "
    "and pass the PR link or reference along verbatim.",
    "For anything else — greetings, questions about what you do, small talk, questions "
    "about an earlier review — answer yourself; don't delegate.",
]


def build_manager(ctx: SlackContext, model_id: str = DEFAULT_MODEL) -> Team:
    """Build the manager Team for one Slack message. The member inherits this model;
    the leader's voice comes entirely from personality.VOICE."""
    model = OpenAIChat(id=model_id, retries=3, exponential_backoff=True)
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
