"""Agent tool: build + publish the portfolio risk roll-up dashboard.

Deterministic (not agent-composed) so the numbers are exact and it's fast: pull every
engagement's risk/sentiment from Memra (one call), enrich the most at-risk with last-sprint
velocity from Jira (best-effort), render a dashboard, publish to Spin, post the link.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Callable

from bott.shared import config
from bott.shared.observability.logging_setup import get_logger
from bott.shared.persistence import store
from bott.skills.portfolio import aggregate, dashboard, history
from bott.skills.sprint_report import render

log = get_logger("bott.skills.portfolio")

_SLUG = "bott-portfolio-risk-rollup"
_CACHE_KEY = "portfolio_last_published"


def _today() -> str:
    """Return today's date in UTC as YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _post_link(channel: str, text: str, thread_ts: str, broadcast: bool) -> None:
    """Post a Slack link message to the given channel (best-effort)."""
    if not channel:
        return
    try:
        from slack_sdk import WebClient

        token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
        if token:
            WebClient(token=token).chat_postMessage(
                channel=channel, text=text,
                thread_ts=thread_ts or None, reply_broadcast=broadcast,
                unfurl_links=False, unfurl_media=False,
            )
    except Exception as e:  # noqa: BLE001 — link post is best-effort
        log.warning("portfolio link post failed: %s", e)


def _engagements() -> list[dict]:
    from bott.shared.context import MemraClient

    res = MemraClient().engagements_at_risk()
    if isinstance(res, dict):
        return res.get("engagements") or []
    return res if isinstance(res, list) else []


def _board_index(boards: list[dict]) -> list[dict]:
    return boards  # already normalized {id,name,type,project_key,project_name}


def _match_board(account: str, boards: list[dict]) -> dict | None:
    """Best-effort match of a Memra account name to a Jira board. Prefers scrum boards."""
    a = (account or "").strip().lower()
    if not a:
        return None
    cands = [b for b in boards
             if a and (a in (b.get("project_name") or "").lower()
                       or a in (b.get("name") or "").lower()
                       or (b.get("project_key") or "").lower() == a)]
    if not cands:
        return None
    scrum = [b for b in cands if b.get("type") == "scrum"]
    return (scrum or cands)[0]


def _enrich(row, boards: list[dict], client) -> None:
    """Fill a row's last-sprint velocity (display string + numeric, for the chart) from
    Jira, best-effort. Leaves the defaults ('—' / None) if it can't be resolved."""
    try:
        board = _match_board(row.account, boards)
        if not board:
            return
        sprint = client.latest_closed_sprint(board["id"])
        if not sprint:
            return
        m = render.compute_metrics(client.sprint_issues(sprint["id"]))
        row.vel_stories = m.stories_delivered
        if m.has_points:
            row.vel_points = m.points_achieved
            row.velocity = f"{render._num(m.points_achieved)} pts · {m.stories_delivered} stories"
        else:
            row.velocity = f"{m.stories_delivered} stories"
    except Exception as e:  # noqa: BLE001 — enrichment is best-effort; never fail the row
        log.warning("velocity enrich failed for %s: %s", row.account, e)


def _resolve_children(rows) -> None:
    """Fill each drill-down child's Slack channel NAME (multi-engagement accounts only). Per
    child: one Memra get_entity (engagement → slack_channel_id) + a channel-name resolve.
    Capped, cached, best-effort — falls back to the channel id, then a short engagement id.
    (Names resolve only in the channel's own workspace; elsewhere you get the id.)"""
    children = [c for r in rows for c in r.children][:40]  # cap total lookups
    if not children:
        return
    from bott.shared.context import MemraClient

    mc = MemraClient()
    token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
    slack = None
    if token:
        from slack_sdk import WebClient

        slack = WebClient(token=token)
    chan_name: dict[str, str | None] = {}
    for c in children:
        eid = c.get("engagement_id", "")
        try:
            rec = mc.get_entity(eid, "engagement")
            rec = rec.get("record") if isinstance(rec, dict) and isinstance(rec.get("record"), dict) else rec
            cid = (rec or {}).get("slack_channel_id")
            if cid and slack is not None:
                if cid not in chan_name:
                    try:
                        chan_name[cid] = "#" + slack.conversations_info(channel=cid)["channel"]["name"]
                    except Exception:  # noqa: BLE001 — private/cross-workspace channel
                        chan_name[cid] = None
                c["channel"] = chan_name[cid] or f"channel {cid}"
            elif cid:
                c["channel"] = f"channel {cid}"
            else:
                c["channel"] = eid[:8] or "engagement"
        except Exception as e:  # noqa: BLE001 — best-effort
            log.warning("child channel resolve failed (%s): %s", eid, e)
            c["channel"] = eid[:8] or "engagement"


def _build_html(top_n: int) -> tuple[str, str]:
    """Returns (title, html). Raises if Memra isn't reachable/empty."""
    pf = aggregate.summarize(_engagements())
    if pf.total == 0:
        raise LookupError("Memra returned no engagements for the portfolio roll-up.")

    _resolve_children(pf.rows)  # resolve channel names for the per-account drill-down rows

    # Enrich the most at-risk rows with Jira velocity (one board listing, matched locally).
    if config.jira_configured():
        try:
            from bott.skills.sprint_report.tool import _jira

            client = _jira()
            boards = client.list_boards()
            for r in pf.rows[: max(1, top_n)]:
                _enrich(r, boards, client)
        except Exception as e:  # noqa: BLE001 — dashboard still renders without Jira
            log.warning("jira enrichment skipped: %s", e)

    # Persist this week's snapshot so trend lines accrue over time, then load the series.
    now = datetime.now(timezone.utc)
    series = history.record_snapshot(now.strftime("%Y-%m-%d"), {
        "total": pf.total, "high": pf.high, "medium": pf.medium, "low": pf.low,
        "declining": pf.declining, "improving": pf.improving, "avg_sentiment": pf.avg_sentiment,
    })
    as_of = f"Axelerant delivery portfolio · as of {now.strftime('%-d %B %Y')}"
    return "Portfolio Risk Roll-up", dashboard.render_portfolio_dashboard(pf, series, as_of)


def publish_portfolio_dashboard(
    channel: str = "", thread_ts: str = "", broadcast: bool = False, top_n: int = 10
) -> str:
    """Build the leadership portfolio risk roll-up — per-engagement risk & sentiment (Memra)
    plus last-sprint delivery velocity (Jira) for the most at-risk — render it as a hosted
    dashboard, publish to Spin, and (if a channel is given) post the link.

    Args:
        channel: Slack channel id to post the dashboard link to.
        thread_ts: when posting in reply to a chat request, the thread to reply in.
        broadcast: with thread_ts, also surface the reply on the channel root
            (Slack's "Also send to channel"). Use true for ad-hoc chat requests.
        top_n: how many of the most at-risk engagements to detail + enrich with Jira velocity.
    """
    if not config.memra_configured():
        return "Memra isn't configured (set MEMRA_CLIENT_ID/SECRET) — the portfolio roll-up needs it."

    # Same-day cache: if we already published today, reuse the URL without rebuilding.
    try:
        raw = store.get_setting(_CACHE_KEY)
        if raw:
            cached = json.loads(raw)
            if cached.get("date") == _today() and cached.get("url"):
                url = cached["url"]
                _post_link(channel=channel, text=f"📊 *Portfolio Risk Roll-up* is ready: {url}",
                           thread_ts=thread_ts, broadcast=broadcast)
                return f"Portfolio dashboard already published today: {url}"
    except Exception as e:  # noqa: BLE001 — cache read is best-effort; proceed to rebuild
        log.warning("portfolio cache read failed, rebuilding: %s", e)

    try:
        title, html = _build_html(top_n)
    except LookupError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        log.error("portfolio dashboard build failed: %s", e)
        return f"Couldn't build the portfolio dashboard ({e})."

    from bott.shared.integrations.spin import get_publisher

    publisher = get_publisher()
    try:
        result = publisher.publish(_SLUG, title, html, channel=channel)
    except Exception as e:  # noqa: BLE001 — fall back to a Slack draft on publish failure
        log.error("portfolio publish failed, falling back to Slack: %s", e)
        from bott.shared.integrations.spin import SlackDraftPublisher

        token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN") or ""
        try:
            result = SlackDraftPublisher(token).publish(_SLUG, title, html, channel=channel)
        except Exception as e2:  # noqa: BLE001
            return f"Built the dashboard but couldn't publish it ({e2})."

    if result.mode == "spin" and result.url:
        try:
            store.set_setting(_CACHE_KEY, json.dumps({"date": _today(), "url": result.url}))
        except Exception as e:  # noqa: BLE001 — cache write is best-effort
            log.warning("portfolio cache write failed: %s", e)
        _post_link(channel=channel, text=f"📊 *{title}* is ready: {result.url}",
                   thread_ts=thread_ts, broadcast=broadcast)

    return result.detail


def portfolio_tools() -> list[Callable]:
    return [publish_portfolio_dashboard]
