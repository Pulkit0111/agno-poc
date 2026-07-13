"""DSM (daily standup) skill — the redesigned, form-driven flow.

Three scheduled moments per team, all threaded under one channel message:
  • open_standup      — post the channel message + "Add my update" button (collection opens)
  • close_standup     — post a summary of everyone's submissions in that thread (pre-read)
  • post_call_summary — after the call, post what was discussed (from Memra) in that thread

The button + modal + storing submissions live in the App Home interactivity router; these
tools are what the scheduler-driven agent calls at each moment. All posts disable link
previews and reply in the round's thread.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from slack_sdk import WebClient

from bott.shared.observability.logging_setup import get_logger
from bott.shared.persistence import action_items, standup

log = get_logger("bott.skills.dsm")


def today_key() -> str:
    """Local date string used to key a standup round (open/close/summary share a day)."""
    tz = os.getenv("BOTT_TIMEZONE", "Asia/Kolkata")
    return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")


def _client() -> Optional[WebClient]:
    token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
    return WebClient(token=token) if token else None


def standup_open_blocks(team: str) -> list[dict]:
    value = str(team or "team")
    return [
        {"type": "section", "text": {"type": "mrkdwn",
         "text": f"🧭 *Standup — {team}*\nAdd your async update before the call — tap below. "
                 "Collection is open until the pre-read posts here."}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "➕ Add my update", "emoji": True},
             "action_id": "add_standup_update", "value": value, "style": "primary"},
        ]},
    ]


def _render_submissions(team: str, resps: list[dict]) -> str:
    if not resps:
        return f"🧭 *Standup pre-read — {team}*\n_No updates were submitted this round._"
    lines = [f"🧭 *Standup pre-read — {team}*", f"_{len(resps)} update(s) submitted_", ""]
    blockers: list[tuple[str, str]] = []
    for r in resps:
        lines.append(f"*<@{r['user']}>*")
        if r.get("yesterday"):
            lines.append(f"• _Yesterday:_ {r['yesterday']}")
        if r.get("today"):
            lines.append(f"• _Today:_ {r['today']}")
        if r.get("blockers"):
            lines.append(f"• _Blockers:_ {r['blockers']}")
            blockers.append((r["user"], r["blockers"]))
        lines.append("")
    if blockers:
        lines.append("*⚠️ Blockers to discuss on the call*")
        lines += [f"• <@{u}>: {b}" for u, b in blockers]
    return "\n".join(lines).strip()


def _render_call_summary(team: str) -> str:
    try:
        from bott.shared.context import MemraClient

        r = MemraClient().ask_context(
            f"Summarize what was discussed in the most recent {team} standup or team meeting: "
            "key decisions, blockers raised, and follow-ups or action items."
        )
    except Exception as e:  # noqa: BLE001
        log.error("call-summary Memra fetch failed: %s", e)
        return f"🗣️ *Call summary — {team}* — couldn't fetch meeting context right now ({e})."
    if not isinstance(r, dict):
        return f"🗣️ *Call summary — {team}*\n{str(r)[:700]}"
    conf = r.get("verdict", "unknown")
    ev = r.get("evidence") or []
    lines = [f"🗣️ *Call summary — {team}*  _(from meeting notes · confidence: {conf})_", ""]
    if not ev:
        lines.append("_No meeting notes found in context for this call yet._")
    else:
        for e in ev[:5]:
            text = (e.get("text") or "").strip()
            if not text:
                continue
            cit = e.get("citation") or {}
            url = cit.get("source_url")
            src = f"  <{url}|{(cit.get('source_title') or 'source')[:50]}>" if url else ""
            lines.append(f"• {text[:220]}{src}")
    return "\n".join(lines).strip()


def _resolve_email(client: WebClient, user_id: str) -> str:
    """Look up a Slack user's verified email via users.info. Empty string on failure — same
    fallback used by the App Home router's own `_resolve_email` closure (slack_home/router.py),
    duplicated here rather than imported since that one closes over a request-scoped client."""
    try:
        info = client.users_info(user=user_id)
        user = info.get("user") or {}
        prof = user.get("profile", {}) or {}
        return prof.get("email") or ""
    except Exception as e:  # noqa: BLE001
        log.warning("dsm: users_info failed for %s: %s", user_id, e)
        return ""


def _capture_blocker_action_items(team: str, date: str, client: WebClient) -> None:
    """For every standup response with a non-empty blocker, auto-capture a personal
    follow-up action item for that responder — deduped per (team, date, user) by checking
    for an existing item with identical text+source rather than a new tracking table.
    Responders whose Slack id can't be resolved to an email are SKIPPED (not stored under
    the raw Slack id) — action_items.user_id is the resolved email everywhere else
    (isolation invariant the console relies on), and a Slack id there would be silently
    unmatchable and un-viewable."""
    for r in standup.responses(team, date):
        blockers = (r.get("blockers") or "").strip()
        if not blockers:
            continue
        user_id = r["user"]
        email = _resolve_email(client, user_id)
        if not email:
            log.warning("dsm: could not resolve email for %s (team %s) — skipping "
                        "blocker action item", user_id, team)
            continue
        text = f"Follow up on your blocker: {blockers[:200]}"
        if action_items.has_item_with_text(email, text, "dsm"):
            continue
        action_items.add_item(email, text, time.time(), source="dsm")


def _post_in_thread(team: str, text: str, what: str) -> str:
    cli = _client()
    if not cli:
        return "No Slack token configured."
    rnd = standup.get_round(team, today_key())
    if not rnd:
        return f"No open standup round for {team} today — nothing to post."
    try:
        cli.chat_postMessage(channel=rnd["channel"], thread_ts=rnd["thread_ts"],
                             text=text, unfurl_links=False, unfurl_media=False)
    except Exception as e:  # noqa: BLE001
        log.error("post %s for %s failed: %s", what, team, e)
        return f"Couldn't post the {what} for {team} ({e})."
    return f"Posted the {what} for {team}."


def open_standup(team: str, channel: str) -> str:
    """Open a standup collection round: post the channel message with the 'Add my update'
    button and remember its thread for the pre-read + call summary.

    Args:
        team: The team id/name.
        channel: Slack channel id to post in.
    """
    if not team:
        return "Can't open a standup without a team name."
    cli = _client()
    if not cli:
        return "No Slack token configured."
    try:
        resp = cli.chat_postMessage(channel=channel, text=f"Standup — {team}",
                                    blocks=standup_open_blocks(team), unfurl_links=False)
        standup.open_round(team, today_key(), channel, resp["ts"])
    except Exception as e:  # noqa: BLE001
        log.error("open_standup %s failed: %s", team, e)
        return f"Couldn't open the standup for {team} ({e})."
    return f"Opened standup collection for {team} in {channel}."


def close_standup(team: str, channel: str) -> str:
    """Close collection and post the pre-read (a summary of all submissions) in the thread.
    Also auto-captures a personal follow-up action item for each blocker-holder — see
    `_capture_blocker_action_items` (idempotent: re-closing the same round never duplicates).

    Args:
        team: The team id/name.
        channel: Slack channel id (unused if a round is on record).
    """
    date = today_key()
    resps = standup.responses(team, date)
    cli = _client()
    if cli is not None:
        _capture_blocker_action_items(team, date, cli)
    return _post_in_thread(team, _render_submissions(team, resps), "pre-read")


def post_call_summary(team: str, channel: str) -> str:
    """After the call, post what was discussed (from Memra meeting notes) in the thread.

    Args:
        team: The team id/name.
        channel: Slack channel id (unused if a round is on record).
    """
    return _post_in_thread(team, _render_call_summary(team), "call summary")


def dsm_tools() -> list[Callable]:
    return [open_standup, close_standup, post_call_summary]
