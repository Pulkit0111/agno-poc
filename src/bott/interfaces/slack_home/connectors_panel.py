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
         "on": "connected", "off": "set SLACK_BOT_TOKEN + SLACK_SIGNING_SECRET",
         "fix": [
             "Set SLACK_BOT_TOKEN (or SLACK_TOKEN) to the app's bot OAuth token.",
             "Set SLACK_SIGNING_SECRET from the app's Basic Information page.",
             "Restart Bott — connectors read config at startup.",
         ]},
        {"name": "GitHub", "ok": _safe(config.github_app_configured),
         "on": "review · build · triage", "off": "set GITHUB_APP_ID + private key",
         "fix": [
             "Create (or locate) the GitHub App and note its App ID.",
             "Set GITHUB_APP_ID and the app's private key (GITHUB_APP_PRIVATE_KEY or a key path).",
             "Install the app on the org/repos Bott should reach, then restart Bott.",
         ]},
        {"name": "Jira", "ok": _safe(config.jira_configured),
         "on": "read-only · org", "off": "set JIRA_BASE_URL + JIRA_EMAIL + JIRA_API_TOKEN",
         "fix": [
             "Set JIRA_BASE_URL to your site URL (https://yourorg.atlassian.net).",
             "Create an API token as the bot user and set JIRA_EMAIL + JIRA_API_TOKEN.",
             "Restart Bott — connectors read config at startup.",
         ]},
        {"name": "Confluence", "ok": _safe(config.confluence_configured),
         "on": "read-only · org", "off": "set CONFLUENCE_URL + credentials",
         "fix": [
             "Set CONFLUENCE_URL to your site's Confluence URL.",
             "Set CONFLUENCE_USERNAME + CONFLUENCE_API_KEY (falls back to the Jira email/token if unset).",
             "Restart Bott — connectors read config at startup.",
         ]},
        {"name": "Memra", "ok": _safe(config.memra_configured),
         "on": "org context", "off": "set MEMRA_CLIENT_ID + MEMRA_CLIENT_SECRET",
         "fix": [
             "Set MEMRA_CLIENT_ID + MEMRA_CLIENT_SECRET for the org's Memra OAuth client.",
             "Confirm MEMRA_TOKEN_ENDPOINT / MEMRA_MCP_ENDPOINT if your org uses non-default URLs.",
             "Restart Bott — connectors read config at startup.",
         ]},
        {"name": "Spin", "ok": _safe(config.spin_configured),
         "on": "page publishing", "off": "set SPIN_API_TOKEN",
         "fix": [
             "Set SPIN_API_TOKEN to a Spin Platform API token.",
             "Confirm SPIN_API_BASE_URL if your org uses a non-default Spin host.",
             "Restart Bott — connectors read config at startup.",
         ]},
        {"name": "Sentry", "ok": _safe(config.sentry_configured),
         "on": "read-only · org", "off": "set SENTRY_ORG_SLUG + SENTRY_API_TOKEN",
         "fix": [
             "Set SENTRY_ORG_SLUG to your Sentry organization slug.",
             "Create an API token with org:read/project:read scopes and set SENTRY_API_TOKEN.",
             "Restart Bott — connectors read config at startup.",
         ]},
        {"name": "Google", "ok": _safe(config.google_delegation_configured),
         "on": "Gmail/Drive/Calendar · read-only", "off": "Workspace admin sets up the service account",
         "fix": [
             "Create a Google Cloud service account and enable domain-wide delegation for it.",
             "In Google Workspace admin, authorize the service account's client ID for the "
             "Gmail/Drive/Calendar read-only scopes.",
             "Set GOOGLE_SERVICE_ACCOUNT_PATH to the downloaded key file's path on the Bott host, "
             "then restart.",
         ]},
        {"name": "Codex", "ok": _safe(codex_tokens.is_connected),
         "on": "org ChatGPT subscription", "off": "an admin connects it below",
         "fix": [
             "Open the Models page in this console.",
             "Click Connect and finish the ChatGPT/Codex device-login flow as an admin.",
             "No environment variables needed — Codex auth is stored per-org once connected.",
         ]},
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
