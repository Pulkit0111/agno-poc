"""Scheduled flows, created on the AgentOS scheduler. Every schedule targets the Bott
agent's run endpoint and embeds ``user_id`` + ``session_id`` in the payload so the
scheduled run executes with the right scope (isolation holds for scheduled runs too —
this is the make-or-break requirement for per-user/per-engagement work).

The agent already has the tools it needs (Memra context, Slack posting); a schedule is
just a cron + a prompt + the scope.
"""

from __future__ import annotations

import json
from typing import Any

from agno.scheduler.manager import ScheduleManager

AGENT_RUN_ENDPOINT = "/agents/bott/runs"


def _mgr(db: Any) -> ScheduleManager:
    return ScheduleManager(db)


def _display(**fields: Any) -> str:
    """Small JSON blob stored in a schedule's `description` so the Slack Home tab can
    render a clean label/channel without re-parsing the agent prompt or the cron."""
    return json.dumps({k: v for k, v in fields.items() if v is not None})


def create_delivery_synthesis(
    db: Any,
    *,
    engagement_id: str,
    channel: str,
    cron: str,
    timezone: str = "UTC",
    account_name: str | None = None,
    band: str | None = None,
):
    """Per-engagement delivery digest: Memra → synthesize → post to a Slack channel.
    Scoped to the engagement (so its running context is isolated by session_id)."""
    message = (
        f"Generate the weekly delivery-synthesis digest for the engagement whose id is "
        f"'{engagement_id}'. First gather the FULL picture with your Memra tools:\n"
        "- engagements_at_risk → find the row whose engagement_id matches, for the risk band, "
        "this week's sentiment, and the trend vs the prior week.\n"
        f"- context_map at the 'engagement' level for entity_id '{engagement_id}' → delivery "
        "health, Jira signals, and any noted blockers or friction.\n\n"
        "Then write a top-tier, scannable Slack digest — genuinely useful at a glance. Use this "
        "exact shape, with the emoji section headers as *bold* lines:\n\n"
        "📊 *Delivery synthesis — <account name>*\n"
        "_<one-line headline: overall health in a single phrase>_\n\n"
        "*🚦 Status*\n"
        "<2-3 plain-English sentences: active or not; risk in words (e.g. 'high risk'), not "
        "'risk_score 0.6'; whether client sentiment is rising / flat / declining vs last week; "
        "and delivery health>\n\n"
        "*⚠️ Top risks*\n"
        "• <the 2-4 risks that matter, one line each>\n\n"
        "*👍 Going well*  (include only if there is something genuine)\n"
        "• <point>\n\n"
        "*👉 Next steps*\n"
        "• <2-3 concrete next actions>\n\n"
        "Rules: refer to the engagement by its human ACCOUNT NAME (the 'account' field), never "
        "the id or any UUID. Plain English only — no raw metric field names. Do NOT include raw "
        "URLs (they clutter the channel with link previews); reference sources in words ('per "
        "this week's sentiment snapshot'). Keep each section tight.\n\n"
        f"Finally, post the finished digest to Slack channel {channel} using your Slack tools."
    )
    return _mgr(db).create(
        name=f"delivery-synthesis:{engagement_id}",
        cron=cron,
        endpoint=AGENT_RUN_ENDPOINT,
        timezone=timezone,
        description=_display(kind="delivery", label=account_name or engagement_id,
                             channel=channel, band=band),
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
        description=_display(kind="concierge", label=user_id),
        payload={
            "message": instruction,
            "user_id": user_id,
            "session_id": f"concierge:{user_id}",
        },
        if_exists="update",
    )


def create_security_digest(
    db: Any,
    *,
    channel: str,
    cron: str,
    timezone: str = "UTC",
    source: str = "drupal",
    window_days: int = 2,
):
    """Scheduled security-advisory digest: fetch the latest advisories and post them to a
    channel. Non-personal 'system' scope (no user data), isolated like every other run."""
    message = (
        "It's the scheduled security check. Call your post_drupal_security_advisories tool "
        f"with channel='{channel}' and window_days={window_days}. That tool fetches the "
        "latest Drupal advisories and posts the digest itself (link previews disabled) — do "
        "not post anything else or add commentary."
    )
    return _mgr(db).create(
        name=f"security-digest:{source}",
        cron=cron,
        endpoint=AGENT_RUN_ENDPOINT,
        timezone=timezone,
        description=_display(kind="security", label=f"{source.title()} advisories", channel=channel),
        payload={
            "message": message,
            "user_id": f"feed:{source}-sa",
            "session_id": f"security:{source}",
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
        description=_display(kind="dsm", phase="pre", label=team_id, channel=channel),
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
        description=_display(kind="dsm", phase="post", label=team_id, channel=channel),
        payload={
            "message": message,
            "user_id": f"team:{team_id}",
            "session_id": f"dsm:{team_id}",
        },
        if_exists="update",
    )
