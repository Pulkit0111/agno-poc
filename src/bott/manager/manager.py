"""The manager — an Agno Team leader that talks like a teammate and delegates.

This is the conversational brain shared by both front doors (Slack + AgentOS HTTP). The
leader holds Bott's personality, chats directly for anything that isn't a task, and
delegates real work to specialist members. Today there is one member (Code Review);
agents 2..N drop in as additional members with distinct roles, no change to this routing
layer.

The team is built ONCE per process and reused, bound to a shared Agno ``SqliteDb`` so
sessions/metrics persist and are visible across Slack and the dashboard.
"""

from __future__ import annotations

from functools import lru_cache

from agno.db.sqlite import SqliteDb
from agno.team import Team, TeamMode

from bott.agents.code_review.member import build_code_review_agent
from bott.shared.config import (
    agentos_db_path,
    manager_api_key,
    manager_base_url,
    manager_model,
)
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


def build_manager(db: SqliteDb | None = None, model_id: str | None = None) -> Team:
    """Build the manager Team bound to a shared db. The member inherits this model; the
    leader's voice comes entirely from personality.VOICE. Uses the (fast) MANAGER_MODEL —
    the heavy review runs separately on REVIEW_MODEL in the worker."""
    model = build_model(
        model_id or manager_model(),
        base_url=manager_base_url(),
        api_key=manager_api_key(),
    )
    return Team(
        id="bott-manager",
        name=NAME,
        model=model,
        members=[build_code_review_agent()],
        mode=TeamMode.coordinate,
        description=IDENTITY,
        instructions=[VOICE, *ROUTING_INSTRUCTIONS],
        db=db,
        telemetry=False,
        markdown=False,
    )


@lru_cache(maxsize=1)
def get_manager() -> Team:
    """Process-wide singleton manager team, bound to the shared AgentOS SqliteDb."""
    return build_manager(db=SqliteDb(db_file=agentos_db_path()))


def run_manager(
    team: Team, text: str, session_id: str | None = None, user_id: str | None = None
) -> str:
    """Run the manager on a user message and return its conversational reply."""
    out = team.run(text, session_id=session_id, user_id=user_id)
    return (out.content or "").strip()
