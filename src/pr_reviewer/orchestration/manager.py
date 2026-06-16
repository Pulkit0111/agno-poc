"""The manager — an Agno Team leader that talks like a teammate and delegates.

This is the conversational front door (Slack). The leader holds Bott's personality,
chats directly for anything that isn't a task, and delegates real work to specialist
members. Today there is one member (Code Review); agents 2..N drop in as additional
members with distinct roles, no change to this routing layer.
"""

from __future__ import annotations

from agno.models.openai import OpenAIChat
from agno.team import Team, TeamMode

from ..config import DEFAULT_MODEL
from .code_review_agent import SlackContext, build_code_review_agent

MANAGER_DESCRIPTION = (
    "You are Bott — a friendly, sharp engineering teammate in Slack. You talk like a "
    "colleague, not a command parser."
)

MANAGER_INSTRUCTIONS = [
    "Reply in 1-2 warm, concise sentences. No corporate fluff, no bullet lists, no internal jargon.",
    "Your team can review GitHub pull requests. When someone wants a PR reviewed, or "
    "follows up on a PR already reviewed in this thread, delegate to the Code Review Agent.",
    "Pass the PR link or reference along verbatim — let the specialist handle parsing.",
    "For anything else — greetings, questions about what you do, small talk, questions "
    "about an earlier review — just answer helpfully yourself; don't delegate.",
    "If someone clearly wants a review but gave no link, ask for the GitHub PR link in a friendly way.",
]


def build_manager(ctx: SlackContext, model_id: str = DEFAULT_MODEL) -> Team:
    """Build the manager Team for one Slack message. The member inherits this model."""
    model = OpenAIChat(id=model_id, retries=3, exponential_backoff=True)
    return Team(
        name="Bott",
        model=model,
        members=[build_code_review_agent(ctx)],
        mode=TeamMode.coordinate,
        description=MANAGER_DESCRIPTION,
        instructions=MANAGER_INSTRUCTIONS,
        telemetry=False,
        markdown=False,
    )


def run_manager(team: Team, text: str) -> str:
    """Run the manager on a user message and return its conversational reply."""
    out = team.run(text)
    return (out.content or "").strip()
