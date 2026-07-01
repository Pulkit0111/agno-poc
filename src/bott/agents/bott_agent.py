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

from bott.agents.build_fix import build_tools
from bott.agents.code_review.member import review_tools
from bott.agents.personality import IDENTITY, VOICE
from bott.agents.triage import triage_tools
from bott.shared import config
from bott.shared.config import bott_model
from bott.shared.identity import require_user_id
from bott.shared.model import build_model
from bott.skills.advisories import security_tools
from bott.skills.connectors.register_all import register_all
from bott.skills.connectors.registry import REGISTRY
from bott.skills.dsm import dsm_tools
from bott.skills.engagement_data import engagement_data_tools
from bott.skills.portfolio import portfolio_tools
from bott.skills.scheduling import scheduling_tools
from bott.skills.skill_authoring import skill_authoring_tools
from bott.skills.sprint_report import sprint_report_tools
from bott.skills.web_publish import web_publish_tools
from bott.skills.workspace_tools import build_workspace_tools

# Explicit allowlist of read-only GithubTools functions exposed to the bot.
# Using include_tools (allowlist) instead of exclude_tools (denylist) so that any
# future write tools added by agno are blocked by default, not silently exposed.
_GITHUB_READ_TOOLS: list[str] = [
    "search_repositories",
    "list_repositories",
    "get_repository",
    "get_repository_languages",
    "get_repository_stars",
    "get_repository_with_stats",
    "list_branches",
    "get_pull_request",
    "get_pull_request_changes",
    "get_pull_request_comments",
    "get_pull_request_count",
    "get_pull_requests",
    "get_pull_request_with_details",
    "list_issues",
    "get_issue",
    "list_issue_comments",
    "get_file_content",
    "get_directory_content",
    "get_branch_content",
    "search_code",
    "search_issues_and_prs",
]


def effective_manager_model() -> str:
    """The agent's model id — the single bott_model() (BOTT_MODEL env, default gpt-5.5).
    No store-setting override: one agent, one model, no hidden hijack."""
    return bott_model()

SKILL_INSTRUCTIONS = [
    "You have a library of skills (listed for you) plus general tools (files, terminal, code) "
    "fenced to a workspace. BEFORE you pick a tool, scan your skill list: if a skill's name or "
    "description matches the request (e.g. 'client weekly status' → the client-weekly-status "
    "skill), you MUST load it with get_skill_instructions and follow it — do not improvise or "
    "grab a similar-looking tool (like a report publisher). Only when NO skill matches do you "
    "compose from general tools directly — never force a task into a near-miss skill. Tasks like "
    "a 'release note' or 'one-pager' are general unless a skill is named for them. "
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
    "For any custom or variant deliverable (a scorecard, a briefing, a weekly status, an answer), "
    "GET THE DATA with a data tool (get_portfolio_risk_data, get_engagement_status, "
    "build_sprint_dossier, get_sprint_history, find_people) and COMPOSE the deliverable yourself, "
    "then publish with publish_web_page. The full report/dashboard tools are only for scheduled runs.",
]


def build_skills() -> Skills:
    """The SKILL.md library (Agent Skills standard). Discovery + activation handled by Agno."""
    return Skills(loaders=[LocalSkills(config.bott_skills_dir())])


def build_agent(user_id: str, db=None) -> Agent:
    user_id = require_user_id(user_id)
    model = build_model("chat")

    tools: list = []
    tools.extend(build_tools())   # Build & fix: plan → approve → implement → draft PR
    tools.extend(review_tools())  # PR review (queue → durable worker runs + posts)
    tools.extend(triage_tools())  # Sentry triage: diagnose → approve → implement
    tools.extend(security_tools())  # Drupal security advisories (digest + chat follow-ups)
    tools.extend(dsm_tools())  # DSM standup: open collection / pre-read / post-call summary
    tools.extend(sprint_report_tools())  # Sprint report: live Jira → designed HTML → Spin
    tools.extend(portfolio_tools())  # Portfolio risk roll-up: Memra + Jira → leadership dashboard
    tools.extend(web_publish_tools())  # General Spin deploy: any HTML → public URL
    tools.extend(engagement_data_tools())  # Engagement status + people lookup (Memra-grounded DATA)
    register_all()
    tools.extend(REGISTRY.all_tools())  # all connectors (Jira/Confluence/Slack/Memra/Gmail) via the registry
    tools.extend(scheduling_tools(db))  # NL schedule create/list/remove (user-scoped)
    slack_token = os.getenv("SLACK_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
    if slack_token:
        from agno.tools.slack import SlackTools

        tools.append(SlackTools(token=slack_token))

    github_token = config.github_token()
    if github_token:
        from agno.tools.github import GithubTools

        tools.append(
            GithubTools(
                access_token=github_token,
                include_tools=_GITHUB_READ_TOOLS,
            )
        )

    skills = build_skills()
    tools.extend(build_workspace_tools(db=db, skills=skills))
    tools.extend(skill_authoring_tools(skills=skills))

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


def build_bott_agent(db=None) -> Agent:
    """Shared interface instance, scoped to the system identity. Per-run isolation still
    rides on the Slack-supplied user_id; this is the single shared agent the interface holds."""
    return build_agent(user_id="system@axelerant.com", db=db)
