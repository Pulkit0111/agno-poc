"""Scheduled flows, created on the AgentOS scheduler. Every schedule targets the Bott
agent's run endpoint and embeds ``user_id`` + ``session_id`` in the payload so the
scheduled run executes with the right scope (isolation holds for scheduled runs too —
this is the make-or-break requirement for per-user/per-engagement work).

The agent already has the tools it needs (Memra context, Slack posting); a schedule is
just a cron + a prompt + the scope.
"""

from __future__ import annotations

from typing import Any

from agno.scheduler.manager import ScheduleManager

AGENT_RUN_ENDPOINT = "/agents/bott/runs"


def _mgr(db: Any) -> ScheduleManager:
    return ScheduleManager(db)


def create_delivery_synthesis(
    db: Any, *, engagement_id: str, channel: str, cron: str, timezone: str = "UTC"
):
    """Per-engagement delivery digest: Memra → synthesize → post to a Slack channel.
    Scoped to the engagement (so its running context is isolated by session_id)."""
    message = (
        f"Generate the delivery-synthesis digest for engagement '{engagement_id}'. "
        "Use your Memra tools (engagements_at_risk, and context_map at the 'engagement' "
        f"level for entity_id '{engagement_id}') to pull delivery status, risk band, and "
        "Jira signals; write a concise digest (status, top risks, next steps) with citations; "
        f"then post it to Slack channel {channel} using your Slack tools."
    )
    return _mgr(db).create(
        name=f"delivery-synthesis:{engagement_id}",
        cron=cron,
        endpoint=AGENT_RUN_ENDPOINT,
        timezone=timezone,
        payload={
            "message": message,
            "user_id": f"engagement:{engagement_id}",
            "session_id": f"delivery:{engagement_id}",
        },
        if_exists="update",
    )


def create_recurring_task(
    db: Any, *, user_id: str, task_name: str, instruction: str, cron: str, timezone: str = "UTC"
):
    """Per-user recurring concierge task. The payload carries the user's user_id so the
    scheduled run loads only that user's memory/context — isolation preserved."""
    return _mgr(db).create(
        name=f"concierge:{user_id}:{task_name}",
        cron=cron,
        endpoint=AGENT_RUN_ENDPOINT,
        timezone=timezone,
        payload={
            "message": instruction,
            "user_id": user_id,
            "session_id": f"concierge:{user_id}",
        },
        if_exists="update",
    )


def create_dsm_precall(
    db: Any, *, team_id: str, channel: str, cron: str, timezone: str = "UTC"
):
    """Pre-call: build a discussion-only standup agenda from async updates and post it."""
    message = (
        f"It's almost standup for team '{team_id}'. Read the recent async updates in this "
        f"channel ({channel}) using your Slack tools, then build a DISCUSSION-ONLY agenda: "
        "include only blockers, decisions needed, cross-person conflicts, or risks worth "
        "discussing live — drop routine status. Keep it tight. Post the agenda to "
        f"{channel}."
    )
    return _mgr(db).create(
        name=f"dsm-precall:{team_id}",
        cron=cron,
        endpoint=AGENT_RUN_ENDPOINT,
        timezone=timezone,
        payload={
            "message": message,
            "user_id": f"team:{team_id}",
            "session_id": f"dsm:{team_id}",
        },
        if_exists="update",
    )


def create_dsm_postcall(
    db: Any, *, team_id: str, channel: str, cron: str, timezone: str = "UTC"
):
    """Post-call: consolidate notes and update the running picture (kept in the team's
    session, so day-to-day context carries forward)."""
    message = (
        f"Standup for team '{team_id}' is done. Read the notes/updates in this channel "
        f"({channel}), consolidate them into a short digest (themes, blockers with owners, "
        "momentum, follow-ups), and compare against the running picture from previous days "
        "(your session history) to flag recurring/stale blockers. Post the consolidation to "
        f"{channel}."
    )
    return _mgr(db).create(
        name=f"dsm-postcall:{team_id}",
        cron=cron,
        endpoint=AGENT_RUN_ENDPOINT,
        timezone=timezone,
        payload={
            "message": message,
            "user_id": f"team:{team_id}",
            "session_id": f"dsm:{team_id}",
        },
        if_exists="update",
    )
