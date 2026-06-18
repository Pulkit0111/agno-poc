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
from bott.agents.personality import IDENTITY, VOICE
from bott.shared.config import (
    SETTING_MANAGER_MODEL,
    manager_api_key,
    manager_base_url,
    manager_model,
    memra_configured,
)
from bott.shared.context import MemraClient, make_memra_tools
from bott.shared.model import build_model
from bott.shared.persistence import store
from bott.skills.advisories import security_tools
from bott.skills.dsm import dsm_tools


def effective_manager_model() -> str:
    """The conversational model id: the persisted setting if present, else the env default."""
    return store.get_setting(SETTING_MANAGER_MODEL) or manager_model()

SKILL_INSTRUCTIONS = [
    "You are one agent with several skills. Use your Memra tools (read-only) to ground "
    "answers about engagements, people, delivery status, risks, and action items — always "
    "prefer cited context over guessing.",
    "When someone asks you to review a GitHub PR (or follows up on one), call start_review "
    "/ start_rereview and then STOP — reply with an empty message, no text at all. The review "
    "engine acknowledges with a reaction and posts live progress + the verdict in this thread.",
    "For personal/concierge questions (a person's action items, tasks, what they own), answer "
    "ONLY for the person you're talking to — scope strictly to them and never surface anyone "
    "else's items. These come from what they've told you (your memory of them). If you have "
    "nothing on record yet, say so warmly and offer to start tracking it (e.g. 'Nothing on "
    "record for you yet — want me to start tracking your action items?') — never return a "
    "blank or a 'couldn't retrieve' error.",
    "When you need to act in Slack beyond replying (post to another channel, etc.), use "
    "your Slack tools.",
    "For Drupal security advisories (a daily digest, or someone asking 'any new Drupal "
    "CVEs?'), use your drupal_security_advisories tool. When a scheduled run tells you to "
    "post the digest verbatim, post the tool's output exactly — don't rewrite it.",
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
    tools.extend(security_tools())  # Drupal security advisories (digest + chat follow-ups)
    tools.extend(dsm_tools())  # DSM standup: open collection / pre-read / post-call summary
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
        # Agentic memory (keyed by user_id): the agent stores/recalls memory only when it
        # decides to — so a trivial "Hi" runs no memory step and shows NO thinking pill,
        # while a message that uses tools/memory still shows the trace. Isolation enforced
        # by always passing user_id per run (scripts/isolation_test.py).
        enable_agentic_memory=True,
        telemetry=False,
        markdown=False,
    )
