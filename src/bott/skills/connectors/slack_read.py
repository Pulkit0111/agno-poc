"""Read a shared Slack thread (parent + replies) from its permalink — read-only."""

from __future__ import annotations

import os
import re
from typing import Callable

from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.connectors.slack")


def _parse(link_or_ts: str) -> tuple[str | None, str | None]:
    """A Slack permalink (…/archives/<CHANNEL>/p<10><6>[?thread_ts=…]) or 'CHANNEL ts'."""
    s = (link_or_ts or "").strip()
    m = re.search(r"/archives/([A-Z0-9]+)/p(\d{10})(\d{6})", s)
    if m:
        channel, ts = m.group(1), f"{m.group(2)}.{m.group(3)}"
        tm = re.search(r"thread_ts=([0-9.]+)", s)
        return channel, (tm.group(1) if tm else ts)
    parts = s.split()
    if len(parts) == 2 and parts[1].replace(".", "").isdigit():
        return parts[0], parts[1]
    return None, None


def read_slack_thread(link_or_ts: str, limit: int = 50) -> str:
    """Read a Slack thread (the parent message + all replies) from a shared link, read-only.

    Args:
        link_or_ts: A Slack thread permalink, or 'CHANNEL_ID 1699999999.000009'.
        limit: Max messages (default 50).
    """
    channel, ts = _parse(link_or_ts)
    if not channel or not ts:
        return ("Couldn't read that — give me a Slack thread link "
                "(…/archives/<CHANNEL>/p<ts>) or 'CHANNEL_ID <ts>'.")
    token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
    if not token:
        return "No Slack token configured."
    try:
        from slack_sdk import WebClient

        msgs = WebClient(token=token).conversations_replies(
            channel=channel, ts=ts, limit=limit).get("messages", [])
    except Exception as e:  # noqa: BLE001
        log.error("read thread %s/%s failed: %s", channel, ts, e)
        return f"Couldn't read that thread ({e})."
    if not msgs:
        return "That thread has no messages I can see (is Bott in the channel?)."
    lines = [f"Slack thread in {channel} — {len(msgs)} message(s):"]
    for m in msgs:
        who = m.get("user") or m.get("bot_id") or "?"
        lines.append(f"- <@{who}>: {(m.get('text') or '').strip()[:600]}")
    return "\n".join(lines)


def slack_read_tools() -> list[Callable]:
    return [read_slack_thread] if (os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")) else []
