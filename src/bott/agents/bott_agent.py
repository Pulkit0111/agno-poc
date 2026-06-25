"""The single Bott agent — one agent with specialized skills (tools), not a team.

Isolation lives at user_id/session_id (the Slack interface supplies both). Skills are
added as tools: Memra context (read-only), Slack posting, and — added incrementally —
PR review, DSM, delivery synthesis, and concierge. Models run via the pluggable backend
(Codex proxy for the POC).
"""

from __future__ import annotations

import os

from agno.agent import Agent
from agno.skills import LocalSkills, Skills

from bott.agents.code_review.member import review_tools
from bott.agents.personality import IDENTITY, VOICE
from bott.shared import config
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
from bott.skills.portfolio import portfolio_tools
from bott.skills.sprint_report import sprint_report_tools
from bott.skills.web_publish import web_publish_tools
from bott.skills.workspace_tools import build_workspace_tools


def effective_manager_model() -> str:
    """The conversational model id: the persisted setting if present, else the env default."""
    return store.get_setting(SETTING_MANAGER_MODEL) or manager_model()

SKILL_INSTRUCTIONS = [
    "You are one agent with a library of skills (loaded on demand) plus general tools "
    "(files, terminal, code) fenced to a workspace, and the ability to search your own past "
    "sessions. Your available skills are listed for you. If one matches the request, you MUST "
    "load it with get_skill_instructions and follow it (don't improvise a one-off). Only work "
    "without a skill when none applies. "
    "If you need something to proceed, just ask for it in plain words in this thread and stop "
    "— the person's next reply continues this same conversation. Never use a separate input "
    "form. When you've worked out a genuinely reusable workflow, you may offer to save it as "
    "a skill (skill_manage) — selectively, not every time.",
    "Use your Memra tools (read-only) to ground answers about engagements, people, delivery "
    "status, risks, and action items — always prefer cited context over guessing.",
    "For personal/concierge questions, answer ONLY for the person you're talking to — scope "
    "strictly to them and never surface anyone else's items.",
    "When you need to act in Slack beyond replying (post to another channel, etc.), use your "
    "Slack tools.",
    "Do dependent file steps in order across turns — after you write a file, trust its "
    "contents; don't re-read it in the same turn (parallel tool calls may race).",
    "Keep replies warm, concise, and specific. Never invent facts; if context is missing, say so.",
    "This message is part of a Slack thread. If you need the full conversation or what others "
    "said, use get_channel_history to read the thread before acting — don't assume; check.",
    "Your publishing tools (web pages, dashboards, reports) RETURN a link; you then share that "
    "link ONCE in your own reply, in your own words. Never call a separate 'post' tool in chat "
    "and never repeat the same link twice.",
]


def build_skills() -> Skills:
    """The SKILL.md library (Agent Skills standard). Discovery + activation handled by Agno."""
    return Skills(loaders=[LocalSkills(config.bott_skills_dir())])


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
    tools.extend(sprint_report_tools())  # Sprint report: live Jira → designed HTML → Spin
    tools.extend(portfolio_tools())  # Portfolio risk roll-up: Memra + Jira → leadership dashboard
    tools.extend(web_publish_tools())  # General Spin deploy: any HTML → public URL
    if memra_configured():
        tools.extend(make_memra_tools(MemraClient()))
    slack_token = os.getenv("SLACK_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
    if slack_token:
        from agno.tools.slack import SlackTools

        tools.append(SlackTools(token=slack_token))

    skills = build_skills()
    tools.extend(build_workspace_tools(db=db, skills=skills))

    return Agent(
        id="bott",
        name="Bott",
        model=model,
        db=db,
        description=IDENTITY,
        instructions=[VOICE, *SKILL_INSTRUCTIONS],
        tools=tools,
        skills=skills,
        num_history_runs=20,
        add_history_to_context=True,
        # Agentic memory (keyed by user_id): the agent stores/recalls memory only when it
        # decides to — so a trivial "Hi" runs no memory step and shows NO thinking pill,
        # while a message that uses tools/memory still shows the trace. Isolation enforced
        # by always passing user_id per run (scripts/isolation_test.py).
        enable_agentic_memory=True,
        telemetry=False,
        markdown=False,
    )
