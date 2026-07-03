# src/bott/interfaces/slack_home/connectors_panel.py
"""App Home 'Connectors' section — a live ✓/✗ of everything Bott can reach.

Status is read straight from the same ``config.*_configured()`` / ``codex_tokens`` checks
the system-status tool uses, so it can't drift. The Home tab re-publishes on every
``app_home_opened``, so a connector flips from ❌ to ✅ the next time the user opens Home —
no restart needed.
"""

from __future__ import annotations

import os

from bott.shared import codex_tokens, config


def _slack_ok() -> bool:
    return bool((os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")) and os.getenv("SLACK_SIGNING_SECRET"))


def connector_statuses() -> list[dict]:
    """One dict per connector: ``{name, ok, meta}``. ``meta`` is a short caption — a role
    when connected, a how-to-fix hint when not."""

    def _safe(fn) -> bool:
        try:
            return bool(fn())
        except Exception:  # noqa: BLE001 — a status probe must never raise into the Home view
            return False

    return [
        {"name": "Slack", "ok": _slack_ok(),
         "on": "connected", "off": "set SLACK_BOT_TOKEN + SLACK_SIGNING_SECRET"},
        {"name": "GitHub", "ok": _safe(config.github_app_configured),
         "on": "review · build · triage", "off": "set GITHUB_APP_ID + private key"},
        {"name": "Jira", "ok": _safe(config.jira_configured),
         "on": "read-only · org", "off": "set JIRA_BASE_URL + JIRA_EMAIL + JIRA_API_TOKEN"},
        {"name": "Confluence", "ok": _safe(config.confluence_configured),
         "on": "read-only · org", "off": "set CONFLUENCE_URL + credentials"},
        {"name": "Memra", "ok": _safe(config.memra_configured),
         "on": "org context", "off": "set MEMRA_CLIENT_ID + MEMRA_CLIENT_SECRET"},
        {"name": "Spin", "ok": _safe(config.spin_configured),
         "on": "page publishing", "off": "set SPIN_API_TOKEN"},
        {"name": "Sentry", "ok": _safe(config.sentry_configured),
         "on": "read-only · org", "off": "set SENTRY_ORG_SLUG + SENTRY_API_TOKEN"},
        {"name": "Google", "ok": _safe(config.google_delegation_configured),
         "on": "Gmail/Drive/Calendar · read-only", "off": "Workspace admin sets up the service account"},
        {"name": "Codex", "ok": _safe(codex_tokens.is_connected),
         "on": "org ChatGPT subscription", "off": "an admin connects it below"},
    ]


def connectors_section(is_admin: bool = False) -> list[dict]:
    """Members get a one-line ✅/❌ chip strip (glance value, no setup noise); admins get
    the full per-connector list with how-to-fix hints (they're the ones who can act)."""
    statuses = connector_statuses()
    connected = sum(1 for s in statuses if s["ok"])
    header = [
        {"type": "header", "text": {"type": "plain_text", "text": "🧩 Connectors", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn",
         "text": f"What I can reach right now · {connected}/{len(statuses)} connected"}]},
    ]
    if not is_admin:
        chips = "  ·  ".join(f"{s['name']} {'✅' if s['ok'] else '❌'}" for s in statuses)
        return header + [{"type": "section", "text": {"type": "mrkdwn", "text": chips}}]
    lines = []
    for s in statuses:
        icon = "✅" if s["ok"] else "❌"
        caption = s["on"] if s["ok"] else s["off"]
        lines.append(f"{icon} *{s['name']}* — {caption}")
    return header + [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]
