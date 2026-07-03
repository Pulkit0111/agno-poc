"""Agentic messaging — send a Slack message now, or schedule a one-off send for later.

Bott has `chat:write`, so it can actually DO "ping me in 2 minutes" or "send X to @person"
instead of deflecting to Slack slash-commands. Sends to the current channel by default (the
reliable path with the current bot scopes); a named person is pinged with a mention there,
a named channel is targeted directly. A future time schedules via Slack's chat.scheduleMessage.

(Deliberately NOT for spammy repeats — recurring "ping every N minutes" is refused by the
agent's judgment, and genuinely recurring digests go through the scheduler.)
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Callable, Optional

from agno.run import RunContext
from agno.tools import tool

from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.skills.messaging")

_REL = re.compile(r"in\s+(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|[smh])\b", re.I)
_UNIT = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
         "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
         "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600}


def _client():
    from slack_sdk import WebClient
    tok = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
    return WebClient(token=tok) if tok else None


def _parse_when(when: str) -> Optional[int]:
    """A future unix timestamp, or None for 'send now'. Accepts 'in N seconds/minutes/hours'
    or an ISO-8601 datetime; anything unrecognized → None (send now)."""
    w = (when or "").strip().lower()
    if not w or w in ("now", "right now", "immediately", "asap"):
        return None
    m = _REL.search(w)
    if m:
        return int(time.time()) + int(m.group(1)) * _UNIT.get(m.group(2).rstrip("."), 60)
    try:
        return int(datetime.fromisoformat((when or "").strip()).timestamp())
    except (ValueError, TypeError):
        return None


def _extract_user_id(recipient: str) -> Optional[str]:
    m = re.match(r"<@([UW][A-Z0-9]+)", recipient or "") or re.match(r"^([UW][A-Z0-9]+)$", (recipient or "").strip())
    return m.group(1) if m else None


def _extract_channel_id(recipient: str) -> Optional[str]:
    m = re.match(r"<#([CG][A-Z0-9]+)", recipient or "") or re.match(r"^([CG][A-Z0-9]+)$", (recipient or "").strip())
    return m.group(1) if m else None


def _current_channel(run_context) -> Optional[str]:
    deps = (getattr(run_context, "dependencies", None) or {}) if run_context else {}
    return deps.get("Slack channel_id")


def _send_impl(run_context, recipient: str, text: str, when: str = "") -> str:
    client = _client()
    if client is None:
        return "Slack isn't configured, so I can't send messages."
    text = (text or "").strip()
    if not text:
        return "What should I say?"

    cur = _current_channel(run_context)
    recipient = (recipient or "").strip()
    ch = _extract_channel_id(recipient)
    uid = _extract_user_id(recipient)
    prefix = ""
    if ch:
        channel = ch
    elif uid:
        # Ping the person in this channel — reliable without the im:write DM scope.
        channel, prefix = cur, f"<@{uid}> "
    else:
        # "me" / "here" / a plain name / empty → the current channel.
        channel = cur
    if not channel:
        return "I can't tell which channel to send to from here — name a channel and I'll post it."

    body = prefix + text
    post_at = _parse_when(when)
    try:
        if post_at:
            client.chat_scheduleMessage(channel=channel, text=body, post_at=post_at)
            return "Done — I'll send that at the time you asked."
        client.chat_postMessage(channel=channel, text=body)
        return "Sent."
    except Exception as e:  # noqa: BLE001
        log.error("send_message failed: %s", e)
        return f"Couldn't send it: {redact(str(e))}"


def messaging_tools() -> list[Callable]:
    @tool(name="send_message")
    def send_message(run_context: RunContext, recipient: str, text: str, when: str = "") -> str:
        """Send a Slack message, now or scheduled for later — use this for "ping me in N
        minutes", "remind me at <time>", or "send/DM <text> to <person/channel>".

        Args:
            recipient: who/where — "me"/"here" for the current channel, a channel (`#name`
                or its id / `<#C…>`), or a person (`<@U…>` mention or user id). A person is
                pinged in the current channel.
            text: the message to send.
            when: empty/"now" to send immediately, or "in N minutes/hours", or an ISO
                datetime, to schedule a one-off send.

        Do NOT use this to set up spammy repeats (e.g. pinging someone every 2 minutes); for
        genuine recurring posts, create a schedule instead.
        """
        return _send_impl(run_context, recipient, text, when)

    return [send_message]
