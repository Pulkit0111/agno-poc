"""The single Bott agent — one agent with specialized skills (tools), not a team.

Isolation lives at user_id/session_id (the Slack interface supplies both). Skills are
added as tools: Memra context (read-only), Slack posting, and — added incrementally —
PR review, DSM, delivery synthesis, and concierge. Models run via the pluggable backend
(Codex proxy for the POC).
"""

from __future__ import annotations

import os

from agno.agent import Agent
from agno.memory import MemoryManager
from agno.skills import LocalSkills, Skills

from bott.agents.build_fix import build_tools
from bott.agents.code_review.member import review_tools
from bott.agents.personality import get_identity, get_voice
from bott.agents.triage import triage_tools
from bott.shared import config
from bott.shared.config import bott_model
from bott.shared.identity import require_user_id
from bott.shared.model import build_model
from bott.skills.action_items import action_items_tools
from bott.skills.advisories import security_tools
from bott.skills.capability_page import capability_page_tools
from bott.skills.channel_map import channel_map_tools
from bott.skills.connectors.register_all import register_all
from bott.skills.connectors.registry import REGISTRY
from bott.skills.dsm import dsm_tools
from bott.skills.engagement_data import engagement_data_tools
from bott.skills.portfolio import portfolio_tools
from bott.skills.repo_access import repo_access_tools
from bott.skills.review_trends import review_trends_tools
from bott.skills.scheduling import scheduling_tools
from bott.skills.skill_authoring import skill_authoring_tools
from bott.skills.sprint_report import sprint_report_tools
from bott.skills.system_status import system_status_tools
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
    "Your tools are served over MCP (the 'bott' server) — call them normally by name.",
    "ALWAYS end your turn with a short reply to the user IN YOUR OWN WORDS — never finish "
    "with an empty message. After you call a tool, don't go silent assuming the tool's "
    "return was the answer: tell the user what you did and what happens next (e.g. after "
    "queuing a PR review, say 'I've queued the review of owner/repo#N — I'll post it in "
    "this thread when it's ready.'). A tool's raw return is NOT shown to the user; only "
    "your reply is.",
    "You have a library of skills (listed for you) plus general tools (files, terminal, code) "
    "fenced to a workspace. BEFORE you pick a tool, scan your skill list: if a skill's name or "
    "description matches the request (e.g. 'client weekly status' → the client-weekly-status "
    "skill), you MUST load it with get_skill_instructions and follow it — do not improvise or "
    "grab a similar-looking tool (like a report publisher). Only when NO skill matches do you "
    "compose from general tools directly — never force a task into a near-miss skill. Tasks like "
    "a 'release note' or 'one-pager' are general unless a skill is named for them. "
    "When a request is CLOSE to a skill or capability but you're not sure it's the right fit "
    "(a near-miss), don't silently guess or force it: reply with one short line — what you CAN "
    "do for it and what you'd need to proceed — and ask. A quick 'I can do X; do you want that, "
    "or did you mean Y?' beats a wrong assumption. "
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


# What the memory manager is allowed to keep. Scoped deliberately: durable facts that
# personalize future conversations (identity, how to be addressed, location, role, stable
# preferences) — NOT transient task chatter or one-off questions. This is the policy that
# replaces the old "only remember when explicitly asked" instruction: a plain declarative
# ("I live in Srinagar", "you can call me skippednote") IS a durable fact and must be kept.
MEMORY_CAPTURE_INSTRUCTIONS = """\
Capture only durable facts about this user that will personalize future conversations:
- Their name and how they want to be addressed.
- Where they are based / their location, timezone, or working hours.
- Their role, team, or the engagements they own.
- Stable preferences about how they want you to work (formatting, defaults, what to avoid).

A plain declarative statement counts — "I live in Srinagar" or "you can call me skippednote"
is a durable fact and MUST be captured even without the words "remember this".

Do NOT capture: transient task requests, one-off questions, the content of a report you just
produced, or anything specific to a single conversation that won't matter next time."""


def build_memory_manager(db=None) -> MemoryManager:
    """Deterministic user-memory capture. Runs after every turn (via update_memory_on_run)
    and extracts durable facts per MEMORY_CAPTURE_INSTRUCTIONS — so a fact the user states in
    one Slack thread is reliably recalled in the next (memory is keyed by user_id; each Slack
    thread is a separate session_id). The extraction pass is one codex exec structured-output
    call (CodexExecMemoryManager) — the tool-calling MemoryManager needs a function-calling
    model, and bott's only LLM path is the codex CLI."""
    from bott.shared.codex_memory import CodexExecMemoryManager

    return CodexExecMemoryManager(
        memory_capture_instructions=MEMORY_CAPTURE_INSTRUCTIONS,
        db=db,
    )


def build_chat_toolkits(db=None, skills: Skills | None = None,
                        include_skill_tools: bool = False) -> list:
    """The full chat tool surface — ONE list consumed by both the Agno agent (historically
    as in-process tools) and the MCP server (which serves the same tools to codex exec).
    `include_skill_tools` adds the Skills access tools (get_skill_instructions, ...) that
    Agno normally injects itself via Agent(skills=...) — the MCP server needs them
    explicitly, the agent must not get them twice."""
    skills = skills or build_skills()
    tools: list = []
    tools.extend(build_tools())   # Build & fix: plan → approve → implement → draft PR
    tools.extend(review_tools())  # PR review (queue → durable worker runs + posts)
    tools.extend(triage_tools())  # Sentry triage: diagnose → approve → implement
    tools.extend(security_tools())  # Drupal security advisories (digest + chat follow-ups)
    tools.extend(dsm_tools())  # DSM standup: open collection / pre-read / post-call summary
    tools.extend(sprint_report_tools())  # Sprint report: live Jira → designed HTML → Spin
    tools.extend(portfolio_tools())  # Portfolio risk roll-up: Memra + Jira → leadership dashboard
    tools.extend(repo_access_tools())  # Repo awareness: list accessible repos + inspect a repo
    tools.extend(system_status_tools())  # Deployment health: what's live/configured
    tools.extend(web_publish_tools())  # General Spin deploy: any HTML → public URL
    tools.extend(capability_page_tools())  # Capability page: "what Bott can do here" → Spin
    tools.extend(review_trends_tools())  # Descriptive PR-review trend stats (verdict/volume; no accuracy metrics)
    tools.extend(engagement_data_tools())  # Engagement status + people lookup (Memra-grounded DATA)
    tools.extend(channel_map_tools())  # Map a Slack channel to an engagement so "this engagement" resolves
    register_all()
    tools.extend(REGISTRY.all_tools())  # all connectors (Jira/Confluence/Slack/Memra/Gmail) via the registry
    tools.extend(scheduling_tools(db))  # NL schedule create/list/remove (user-scoped)
    tools.extend(action_items_tools())  # Personal action items: add/list/done/snooze (user-scoped)
    slack_token = os.getenv("SLACK_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
    if slack_token:
        from agno.tools.slack import SlackTools

        # Read/search Slack, but do NOT let the agent SEND messages: the Slack interface
        # already posts the agent's reply to the thread. Giving it send tools made it post
        # the answer AND a redundant "Done — I replied…" message (the double-post seen in chat).
        tools.append(SlackTools(
            token=slack_token,
            enable_send_message=False,
            enable_send_message_thread=False,
        ))

    github_token = config.github_token()
    if github_token:
        from agno.tools.github import GithubTools

        tools.append(
            GithubTools(
                access_token=github_token,
                include_tools=_GITHUB_READ_TOOLS,
            )
        )

    tools.extend(build_workspace_tools(db=db, skills=skills))
    tools.extend(skill_authoring_tools(skills=skills))
    if include_skill_tools:
        tools.extend(skills.get_tools())
    return tools


def build_agent(user_id: str, db=None) -> Agent:
    user_id = require_user_id(user_id)
    model = build_model("chat")
    skills = build_skills()

    return Agent(
        id="bott",
        name="Bott",
        model=model,
        db=db,
        description=get_identity(),
        instructions=[get_voice(), *SKILL_INSTRUCTIONS],
        # NO in-process Agno tools: the model is CodexExecChat (codex exec), whose own loop
        # calls the SAME toolkits over bott's MCP server (interfaces/mcp/) — see
        # build_chat_toolkits above. Per-user workspace scoping moved with them: the MCP
        # dispatcher applies workspace_scope(user_id) from the verified bearer ticket, so
        # the scope_workspace_to_user tool hook has nothing to wrap here anymore.
        tools=[],
        skills=skills,
        num_history_runs=20,
        add_history_to_context=True,
        # Deterministic user memory (keyed by user_id). The memory manager runs after every
        # turn and captures durable facts per MEMORY_CAPTURE_INSTRUCTIONS — guaranteed capture,
        # unlike the old enable_agentic_memory path, where the write was discretionary and
        # silently skipped plain declaratives ("I live in Srinagar") while the reply still
        # claimed "I've noted that". Recall stays automatic: stored memories for this user_id
        # are injected into context on every run (add_memories_to_context defaults True), so a
        # fact stated in one Slack thread surfaces in the next. update_memory_on_run and
        # enable_agentic_memory are mutually exclusive — do NOT set both. Isolation is enforced
        # by always passing user_id per run (scripts/isolation_test.py).
        update_memory_on_run=True,
        memory_manager=build_memory_manager(db),
        # Explicit (Agno would infer True from the above anyway): recall this user's stored
        # memories into context on every run, so cross-thread facts actually surface.
        add_memories_to_context=True,
        telemetry=False,
        markdown=False,
    )


def build_bott_agent(db=None) -> Agent:
    """Shared interface instance, scoped to the system identity. Per-run isolation still
    rides on the Slack-supplied user_id; this is the single shared agent the interface holds."""
    return build_agent(user_id="system@axelerant.com", db=db)
