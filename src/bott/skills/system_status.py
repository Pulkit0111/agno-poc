"""system_status tool — reports what's live/configured in this Bott deployment.

Single plain function (mirrors the connector tool pattern). Returns a compact,
Slack-mrkdwn-friendly status grouped by concern. No secret values are shown;
only presence/status markers.
"""

from __future__ import annotations

import os
from typing import Callable

from bott.interfaces.slack_home.models import _active
from bott.shared import codex_cli, config


def system_status() -> str:
    """Report which tools, connectors, and services are live in this Bott deployment.

    Useful for questions like "what tools are available?", "is Jira connected?",
    "how do I connect Gmail?", or "what model is active?". Returns a human-readable
    grouped status — no secret values, only presence/configuration markers.
    """
    lines: list[str] = ["*Bott System Status*\n"]

    # ── Model ──────────────────────────────────────────────────────────────────
    lines.append("*Model*")
    try:
        active = _active()
        provider = active.get("provider", "?")
        chat = active.get("chat", "?")
        build = active.get("build", "?")
        review = active.get("review", "?")
        lines.append(f"✅ Provider: `{provider}`  ·  chat: `{chat}`  ·  build: `{build}`  ·  review: `{review}`")
        if build == review:
            lines.append("⚠️  review = build — the reviewer is auto-swapped at run time "
                         "(anti-affinity); set model.review to choose it explicitly.")
    except Exception:  # noqa: BLE001
        lines.append("⚠️  Could not read active model settings.")
    try:
        codex_ok = codex_cli.is_logged_in()
    except Exception:  # noqa: BLE001
        codex_ok = False
    if codex_ok:
        lines.append("✅ Org Codex (ChatGPT subscription): connected")
    else:
        lines.append("⚠️  Org Codex: not connected — an admin can connect it via App Home → Models.")

    # ── Data / Database ────────────────────────────────────────────────────────
    lines.append("\n*Data / DB*")
    if config.database_url():
        lines.append("✅ Database: Postgres")
    else:
        lines.append("⚠️  Database: SQLite (local dev) — set DATABASE_URL for production.")

    # ── Slack ──────────────────────────────────────────────────────────────────
    lines.append("\n*Slack*")
    bot_token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
    signing_secret = os.getenv("SLACK_SIGNING_SECRET")
    if bot_token:
        lines.append("✅ Bot token: present")
    else:
        lines.append("⚠️  Bot token: missing (set SLACK_BOT_TOKEN)")
    if signing_secret:
        lines.append("✅ Signing secret: present")
    else:
        lines.append("⚠️  Signing secret: missing (set SLACK_SIGNING_SECRET)")

    # ── GitHub ─────────────────────────────────────────────────────────────────
    lines.append("\n*GitHub*")
    if config.github_app_configured():
        lines.append("✅ GitHub App: configured (build / review / triage PRs enabled)")
    else:
        lines.append(
            "⚠️  GitHub App: not configured — set GITHUB_APP_ID + private key "
            "(GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH) + GITHUB_WEBHOOK_SECRET."
        )

    # ── Connectors ─────────────────────────────────────────────────────────────
    lines.append("\n*Connectors*")

    # Jira
    if config.jira_configured():
        lines.append("✅ Jira: configured (shared org credential, read-only)")
    else:
        lines.append(
            "⚠️  Jira: not configured — set JIRA_BASE_URL + JIRA_EMAIL + JIRA_API_TOKEN."
        )

    # Confluence
    if config.confluence_configured():
        lines.append("✅ Confluence: configured (shared org credential, read-only)")
    else:
        lines.append(
            "⚠️  Confluence: not configured — set CONFLUENCE_URL (or reuse Jira's site) "
            "+ CONFLUENCE_USERNAME + CONFLUENCE_API_KEY (or reuse Jira's token)."
        )

    # Sentry
    if config.sentry_configured():
        lines.append("✅ Sentry: configured (shared org credential, read-only)")
    else:
        lines.append(
            "⚠️  Sentry: not configured — set SENTRY_ORG_SLUG + SENTRY_API_TOKEN (Sentry admin)."
        )

    # Memra
    if config.memra_configured():
        lines.append("✅ Memra: configured (org context layer, read-only)")
    else:
        lines.append(
            "⚠️  Memra: not configured — set MEMRA_CLIENT_ID + MEMRA_CLIENT_SECRET."
        )

    # Spin
    if config.spin_configured():
        lines.append("✅ Spin: configured (sprint-report publishing enabled)")
    else:
        lines.append(
            "⚠️  Spin: not configured — set SPIN_API_TOKEN to enable report publishing."
        )

    # Google (Gmail / Drive / Calendar)
    if config.google_delegation_configured():
        lines.append(
            "✅ Google (Gmail/Drive/Calendar): configured — reads *your own* data by "
            "impersonating the verified Slack caller (read-only, org service account)."
        )
    else:
        lines.append(
            "⚠️  Google (Gmail/Drive/Calendar): not configured.\n"
            "    ℹ️  Gmail/Drive/Calendar are *org-level, read-only* connectors configured "
            "once by a Workspace admin (a service account with domain-wide delegation) — "
            "there is *no per-user 'connect' step*; pending `GOOGLE_SERVICE_ACCOUNT_PATH` "
            "+ the admin authorizing the `.readonly` scopes. Once set up, Bott reads *your "
            "own* data by impersonating the verified Slack caller."
        )

    # ── Scheduler / Admins ─────────────────────────────────────────────────────
    lines.append("\n*Scheduler / Admins*")
    lines.append("✅ Scheduler: on (AgentOS runs with scheduler=True)")
    n_admins = len(config.bott_admins())
    if n_admins:
        lines.append(f"✅ Admins configured: {n_admins}")
    else:
        lines.append(
            "⚠️  No admins configured — set BOTT_ADMINS (comma-separated emails) "
            "to enable model switching and Codex connection."
        )

    return "\n".join(lines)


def system_status_tools() -> list[Callable]:
    return [system_status]
