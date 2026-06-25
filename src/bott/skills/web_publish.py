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


def _brand_wrap(title: str, body_html: str) -> str:
    """Wrap a bare HTML fragment in an Axelerant-branded full-document shell."""
    safe_title = (title or "Page").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --orange:#FF5C00;--navy:#0D1B2A;--navy2:#111827;
  --off:#F1F3F5;--slate:#4B5563;--line:#e5e7eb;
  --fh:'Inter',sans-serif;--fd:'Space Grotesk',sans-serif
}}
body{{font-family:var(--fh);background:var(--off);color:var(--navy2);min-height:100vh}}
.ax-header{{
  background:var(--navy);color:#fff;padding:14px 28px;
  display:flex;align-items:center;gap:12px;
  border-bottom:3px solid var(--orange)
}}
.ax-header .ax-logo{{
  font-family:var(--fd);font-weight:700;font-size:1.15rem;letter-spacing:-.01em;
  color:#fff;text-decoration:none
}}
.ax-header .ax-logo span{{color:var(--orange)}}
.ax-header .ax-title{{
  font-size:.875rem;font-weight:500;color:rgba(255,255,255,.65);
  border-left:1px solid rgba(255,255,255,.2);padding-left:12px;margin-left:4px
}}
.ax-content{{max-width:960px;margin:32px auto;padding:0 24px 48px}}
</style>
</head>
<body>
<header class="ax-header">
  <a class="ax-logo" href="#">Axelerant<span>.</span></a>
  <span class="ax-title">{safe_title}</span>
</header>
<main class="ax-content">
{body_html}
</main>
</body>
</html>"""


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
        channel: Accepted for back-compat but unused — the agent shares the link in its reply.
        thread_ts: Accepted for back-compat but unused.
        broadcast: Accepted for back-compat but unused.
    """
    if workspace_file and not html:
        path = os.path.join(config.bott_workspace_dir(), os.path.basename(workspace_file))
        if not os.path.isfile(path):
            return f"No such file in your workspace: {os.path.basename(workspace_file)}."
        with open(path, encoding="utf-8") as f:
            html = f.read()
    if not html.strip():
        return "Nothing to publish — give me HTML or a workspace .html file."
    html_stripped = html.strip()
    if not re.search(r"<!doctype|<html", html_stripped[:200], re.IGNORECASE):
        html = _brand_wrap(name or "Page", html_stripped)
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
    if result.url:
        return f"Published: {result.url} — share this link with the user."
    return result.detail


def web_publish_tools() -> list[Callable]:
    return [publish_web_page]
