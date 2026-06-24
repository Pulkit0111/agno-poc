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

# Every schedule fires an HTTP call to the agent's own run endpoint. The Agno poller
# starts inside FastAPI lifespan startup and immediately fires any *overdue* (catch-up)
# schedule — e.g. a daily digest whose time passed while the server was down. That
# firing can race uvicorn and hit the port before it's accepting connections, surfacing
# as "All connection attempts failed". Retries absorb that boot race (and any transient
# blip): attempt 1 may fail, a few seconds later the server is up and attempt 2 lands.
_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 15


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
        max_retries=_MAX_RETRIES,
        retry_delay_seconds=_RETRY_DELAY_SECONDS,
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
        max_retries=_MAX_RETRIES,
        retry_delay_seconds=_RETRY_DELAY_SECONDS,
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
        max_retries=_MAX_RETRIES,
        retry_delay_seconds=_RETRY_DELAY_SECONDS,
        if_exists="update",
    )


def create_sentiment_report(db: Any, *, channel: str, cron: str, timezone: str = "UTC"):
    """Scheduled portfolio sentiment / delivery-health digest: roll up every active
    engagement's sentiment + risk from Memra and post a scannable Slack digest. Non-personal
    'portfolio' scope (no single user's data), isolated like every other run."""
    message = (
        "It's the scheduled delivery-health check. Use your memra_engagements_at_risk tool to "
        "pull every active engagement's risk band, this-week sentiment, and trend vs the prior "
        "week, then write a tight, scannable PORTFOLIO digest using this exact shape, with the "
        "emoji section headers as *bold* lines:\n\n"
        "📊 *Delivery health — portfolio*\n"
        "_<one-line headline: overall mood, e.g. 'Mostly steady; 3 accounts need attention'>_\n\n"
        "*🔻 Declining this week*\n"
        "• <account> — <high/medium/low> risk, sentiment down vs last week\n\n"
        "*📈 Improving*  (include only if there is any)\n"
        "• <account> — sentiment up\n\n"
        "*⚠️ Top at-risk*\n"
        "• <account> — one-line why\n\n"
        "Rules: refer to engagements by their ACCOUNT NAME, never ids/UUIDs. State risk in words "
        "('high risk'), never a raw score. Plain English, one line each, and only include a "
        "section if it has content. No raw URLs. "
        f"Finally, post the finished digest to Slack channel {channel} using your Slack tools — "
        "post only the digest, no extra commentary."
    )
    return _mgr(db).create(
        name="sentiment-report:portfolio",
        cron=cron,
        endpoint=AGENT_RUN_ENDPOINT,
        timezone=timezone,
        description=_display(kind="sentiment", label="Delivery health (portfolio)", channel=channel),
        payload={
            "message": message,
            "user_id": "portfolio:delivery-health",
            "session_id": "sentiment-report",
        },
        max_retries=_MAX_RETRIES,
        retry_delay_seconds=_RETRY_DELAY_SECONDS,
        if_exists="update",
    )


def create_portfolio_dashboard(db: Any, *, channel: str, cron: str, timezone: str = "UTC"):
    """Scheduled leadership portfolio risk roll-up: per-engagement risk/sentiment (Memra) +
    last-sprint velocity (Jira) → a Spin dashboard, link posted to a channel. Non-personal
    'portfolio' scope, isolated like every other run."""
    message = (
        "It's the scheduled portfolio risk roll-up. Call your publish_portfolio_dashboard tool "
        f"with channel='{channel}'. That tool aggregates risk/sentiment and delivery velocity, "
        "renders the dashboard, publishes it to Spin, and posts the link itself — do not add any "
        "other commentary."
    )
    return _mgr(db).create(
        name="portfolio-dashboard:risk-rollup",
        cron=cron,
        endpoint=AGENT_RUN_ENDPOINT,
        timezone=timezone,
        description=_display(kind="portfolio", label="Portfolio risk roll-up", channel=channel),
        payload={
            "message": message,
            "user_id": "portfolio:risk-rollup",
            "session_id": "portfolio-dashboard",
        },
        max_retries=_MAX_RETRIES,
        retry_delay_seconds=_RETRY_DELAY_SECONDS,
        if_exists="update",
    )


def create_sprint_report(
    db: Any,
    *,
    engagement: str,
    cron: str,
    timezone: str = "UTC",
    channel: str = "",
):
    """Scheduled per-engagement sprint report: gather live Jira facts, synthesize the
    narrative, render the designed HTML page, publish it (Spin, or a Slack draft fallback),
    and post the link. ``engagement`` is a Jira project key (e.g. 'PADI'). The board is
    discovered automatically. Channel defaults to Memra resolution; pass ``channel`` to pin it.
    Scoped by engagement so the run is isolated like every other."""
    key = engagement.upper()
    channel_step = (
        f"post it to channel '{channel}'"
        if channel
        else "resolve this engagement's Slack channel with your Memra tools and post the link there"
    )
    message = (
        f"It's the scheduled sprint report for the '{key}' engagement. First call "
        f"build_sprint_dossier with engagement='{key}' to get the live Jira facts. Then compose "
        "a report tailored to this engagement (pick meaningful blocks: delivered/next-sprint "
        "tables, risks & blockers from the incomplete/carry-over items, highlights, and client "
        "actions including the UAT/board link) and call publish_sprint_report with "
        f"engagement='{key}', your report_json, only_if_new=true, and the channel. To deliver it, "
        f"{channel_step}. The "
        "only_if_new flag means it will quietly skip if this sprint was already reported — that's "
        "expected; just stop. Do not restate the metrics or story lists, and add no other commentary."
    )
    return _mgr(db).create(
        name=f"sprint-report:{key}",
        cron=cron,
        endpoint=AGENT_RUN_ENDPOINT,
        timezone=timezone,
        description=_display(kind="sprint", label=key, channel=channel or None),
        payload={
            "message": message,
            "user_id": f"engagement:{key}",
            "session_id": f"sprint-report:{key}",
        },
        max_retries=_MAX_RETRIES,
        retry_delay_seconds=_RETRY_DELAY_SECONDS,
        if_exists="update",
    )


def schedule_sprint_reports_for_all(db: Any, *, cron: str, timezone: str = "UTC") -> list[str]:
    """Roll the sprint report out to EVERY engagement in one go: discover all Jira boards and
    create a per-engagement schedule for each (channel left to Memra resolution at run time).
    Returns the project keys scheduled. New engagements get picked up on the next run of this."""
    from bott.skills.sprint_report.tool import _jira

    keys: list[str] = []
    for board in _jira().list_boards():
        key = (board.get("project_key") or "").strip()
        if not key:
            continue
        create_sprint_report(db, engagement=key, cron=cron, timezone=timezone)
        keys.append(key.upper())
    return keys


def _dsm_schedule(db: Any, *, team_id: str, channel: str, cron: str, timezone: str,
                  phase: str, message: str):
    return _mgr(db).create(
        name=f"dsm-{phase}:{team_id}",
        cron=cron,
        endpoint=AGENT_RUN_ENDPOINT,
        timezone=timezone,
        description=_display(kind="dsm", phase=phase, label=team_id, channel=channel),
        payload={
            "message": message,
            "user_id": f"team:{team_id}",
            "session_id": f"dsm:{team_id}",
        },
        max_retries=_MAX_RETRIES,
        retry_delay_seconds=_RETRY_DELAY_SECONDS,
        if_exists="update",
    )


def create_dsm_open(db: Any, *, team_id: str, channel: str, cron: str, timezone: str = "UTC"):
    """Open collection: post the channel message + 'Add my update' button (form-driven)."""
    return _dsm_schedule(
        db, team_id=team_id, channel=channel, cron=cron, timezone=timezone, phase="open",
        message=(
            f"It's standup-open time for team '{team_id}'. Call your open_standup tool with "
            f"team='{team_id}' and channel='{channel}'. Do nothing else."
        ),
    )


def create_dsm_preread(db: Any, *, team_id: str, channel: str, cron: str, timezone: str = "UTC"):
    """Pre-read: close collection and post a summary of submissions in the thread."""
    return _dsm_schedule(
        db, team_id=team_id, channel=channel, cron=cron, timezone=timezone, phase="preread",
        message=(
            f"Standup collection is closing for team '{team_id}'. Call your close_standup tool "
            f"with team='{team_id}' and channel='{channel}'. Do nothing else."
        ),
    )


def create_dsm_callsummary(db: Any, *, team_id: str, channel: str, cron: str, timezone: str = "UTC"):
    """Post-call: fetch what was discussed (Memra) and post it in the same thread."""
    return _dsm_schedule(
        db, team_id=team_id, channel=channel, cron=cron, timezone=timezone, phase="callsummary",
        message=(
            f"The '{team_id}' standup call is done. Call your post_call_summary tool with "
            f"team='{team_id}' and channel='{channel}'. Do nothing else."
        ),
    )
