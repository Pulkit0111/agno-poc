"""General web-publishing tool: deploy any HTML to Spin and return the link.

A shared primitive — usable by ANY request, not tied to a skill (the agent composes it
however the user asks). Mirrors the Spin path the sprint/portfolio skills use."""

from __future__ import annotations

import os
import re
from typing import Callable

from bott.shared import config
from bott.shared.integrations.spin import get_publisher
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.skills.web_publish")


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]", "-", (name or "page").strip().lower()).strip("-") or "page"
    return f"bott-{s}"[:32].rstrip("-")


def _post_link(*, channel: str, text: str, thread_ts: str, broadcast: bool) -> None:
    token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
    if not (token and channel):
        return
    from slack_sdk import WebClient

    WebClient(token=token).chat_postMessage(
        channel=channel, text=text, thread_ts=thread_ts or None,
        reply_broadcast=broadcast, unfurl_links=False, unfurl_media=False,
    )


def publish_web_page(
    name: str, html: str = "", workspace_file: str = "",
    channel: str = "", thread_ts: str = "", broadcast: bool = False,
) -> str:
    """Deploy an HTML page to Spin (a hosted public URL) and return the link. Use this for ANY
    'make a web page / deploy this HTML / give me a shareable link' request.

    Args:
        name: A short title for the page (used for the URL and the heading).
        html: The full HTML source. Provide this OR workspace_file.
        workspace_file: Name of a .html file you wrote in your workspace to publish instead.
        channel: Slack channel id to post the link to (optional).
        thread_ts: post the link in this thread (optional).
        broadcast: with thread_ts, also surface it on the channel (use true for ad-hoc chat).
    """
    if workspace_file and not html:
        path = os.path.join(config.bott_workspace_dir(), os.path.basename(workspace_file))
        if not os.path.isfile(path):
            return f"No such file in your workspace: {os.path.basename(workspace_file)}."
        with open(path, encoding="utf-8") as f:
            html = f.read()
    if not html.strip():
        return "Nothing to publish — give me HTML or a workspace .html file."
    slug, title = _slug(name), (name or "Page")
    try:
        result = get_publisher().publish(slug, title, html, channel=channel)
    except Exception as e:  # noqa: BLE001 — fall back to a Slack draft
        log.error("web publish failed, slack fallback: %s", e)
        from bott.shared.integrations.spin import SlackDraftPublisher

        token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN") or ""
        try:
            result = SlackDraftPublisher(token).publish(slug, title, html, channel=channel)
        except Exception as e2:  # noqa: BLE001
            return f"Couldn't publish the page ({e2})."
    if result.mode == "spin" and result.url and channel:
        try:
            _post_link(channel=channel, text=f"🔗 *{title}* is live: {result.url}",
                       thread_ts=thread_ts, broadcast=broadcast)
        except Exception as e:  # noqa: BLE001 — published; posting is best-effort
            log.warning("published page but link post failed: %s", e)
    return result.detail


def web_publish_tools() -> list[Callable]:
    return [publish_web_page]
