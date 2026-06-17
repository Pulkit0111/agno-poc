"""The single Bott agent — one agent with specialized skills (tools), not a team.

Isolation lives at user_id/session_id (the Slack interface supplies both). Skills are
added as tools: Memra context (read-only), Slack posting, and — added incrementally —
PR review, DSM, delivery synthesis, and concierge. Models run via the pluggable backend
(Codex proxy for the POC).
"""

from __future__ import annotations

import os

from agno.agent import Agent

from bott.agents.code_review.member import review_tools
from bott.manager.manager import effective_manager_model
from bott.manager.personality import IDENTITY, VOICE
from bott.shared.config import manager_api_key, manager_base_url, memra_configured
from bott.shared.context import MemraClient, make_memra_tools
from bott.shared.model import build_model

SKILL_INSTRUCTIONS = [
    "You are one agent with several skills. Use your Memra tools (read-only) to ground "
    "answers about engagements, people, delivery status, risks, and action items — always "
    "prefer cited context over guessing.",
    "When someone asks you to review a GitHub PR (or follows up on one), call start_review "
    "/ start_rereview — the engine runs the review and posts the verdict; you just queue it "
    "and reply in one short sentence.",
    "For personal/concierge questions (a person's action items, their tasks, what they own), "
    "answer ONLY for the person you're currently talking to — use their identity to scope "
    "Memra/get_person lookups, and never surface another person's items.",
    "When you need to act in Slack beyond replying (post to another channel, etc.), use "
    "your Slack tools.",
    "Keep replies warm, concise, and specific. Never invent facts; if context is missing, "
    "say so.",
]


def build_bott_agent(db=None) -> Agent:
    model = build_model(
        effective_manager_model(),
        base_url=manager_base_url(),
        api_key=manager_api_key(),
    )

    tools: list = []
    tools.extend(review_tools())  # PR review (queue → durable worker runs + posts)
    if memra_configured():
        tools.extend(make_memra_tools(MemraClient()))
    slack_token = os.getenv("SLACK_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
    if slack_token:
        from agno.tools.slack import SlackTools

        tools.append(SlackTools(token=slack_token))

    return Agent(
        id="bott",
        name="Bott",
        model=model,
        db=db,
        description=IDENTITY,
        instructions=[VOICE, *SKILL_INSTRUCTIONS],
        tools=tools,
        add_history_to_context=True,
        # Per-user memory (keyed by user_id) — powers concierge recall; isolation is
        # enforced by always passing user_id on every run (see scripts/isolation_test.py).
        enable_user_memories=True,
        telemetry=False,
        markdown=False,
    )
