"""Live connector health probes — one authenticated round-trip per connector, reusing the
SAME client constructors the read tools already build (no new auth paths, no new env vars).

``probe(name, subject_email=None) -> {"ok": bool, "message": str}`` is the only public
entry point. An unknown ``name`` raises ``KeyError`` (the console router turns that into a
404); every KNOWN probe is wrapped so a network/auth failure never raises past this
module — it comes back as ``{"ok": False, "message": <plain-language text incl. the
exception>}`` instead. Codex needs no network at all (``codex_tokens.is_connected()``).

Gmail/Drive/Calendar are domain-delegated: the caller must pass the acting admin's email
as ``subject_email`` (the console router supplies the signed-in admin's own address) since
there is no single default mailbox to impersonate.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Callable, Optional

from bott.shared import codex_tokens, config
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.connectors.probes")

_TIMEOUT = 10.0


def _jira() -> dict:
    if not config.jira_configured():
        return {"ok": False, "message": "Jira isn't configured (set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)."}
    from bott.shared.integrations.jira import JiraClient

    client = JiraClient(
        base_url=config.jira_base_url(),  # type: ignore[arg-type]
        email=config.jira_email(),  # type: ignore[arg-type]
        api_token=config.jira_api_token(),  # type: ignore[arg-type]
        story_points_field=config.jira_story_points_field(),
        timeout=_TIMEOUT,
    )
    me = client._get("/rest/api/3/myself")
    who = me.get("displayName") or me.get("emailAddress") or "the configured account"
    return {"ok": True, "message": f"Connected to Jira as {who}."}


def _confluence() -> dict:
    if not config.confluence_configured():
        return {"ok": False, "message": "Confluence isn't configured (set CONFLUENCE_URL + credentials)."}
    from agno.tools.confluence import ConfluenceTools

    tools = ConfluenceTools(
        url=config.confluence_url(),
        username=config.confluence_username(),
        api_key=config.confluence_api_key(),
    )
    spaces = tools.confluence.get_all_spaces(start=0, limit=1)
    count = len((spaces or {}).get("results") or [])
    return {"ok": True, "message": f"Reached Confluence ({count} space listed)."}


def _slack() -> dict:
    token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
    if not token or not os.getenv("SLACK_SIGNING_SECRET"):
        return {"ok": False, "message": "Slack isn't configured (set SLACK_BOT_TOKEN + SLACK_SIGNING_SECRET)."}
    from slack_sdk import WebClient

    resp = WebClient(token=token, timeout=int(_TIMEOUT)).auth_test()
    team = resp.get("team") or "your workspace"
    return {"ok": True, "message": f"Connected to Slack as the bot in {team}."}


def _memra() -> dict:
    if not config.memra_configured():
        return {"ok": False, "message": "Memra isn't configured (set MEMRA_CLIENT_ID + MEMRA_CLIENT_SECRET)."}
    from bott.shared.context.memra import MemraClient

    tool_names = MemraClient(timeout=_TIMEOUT).list_tools()
    return {"ok": True, "message": f"Reached Memra ({len(tool_names)} tool(s) available)."}


def _sentry() -> dict:
    if not config.sentry_configured():
        return {"ok": False, "message": "Sentry isn't configured (set SENTRY_ORG_SLUG + SENTRY_API_TOKEN)."}
    from bott.shared.integrations.sentry import SentryClient

    client = SentryClient(
        base_url=config.sentry_base_url(),  # type: ignore[arg-type]
        org_slug=config.sentry_org_slug(),  # type: ignore[arg-type]
        api_token=config.sentry_api_token(),  # type: ignore[arg-type]
        timeout=int(_TIMEOUT),
    )
    client.list_issues(limit=1)
    return {"ok": True, "message": f"Reached Sentry org '{config.sentry_org_slug()}'."}


def _codex() -> dict:
    if codex_tokens.is_connected():
        return {"ok": True, "message": "Codex is connected — using the org's ChatGPT subscription."}
    return {"ok": False, "message": "Codex isn't connected. An admin can connect it from the Models page."}


# ── Google (Gmail/Drive/Calendar) — domain-delegated, needs the acting admin's email ──

def _gmail_probe(subject_email: Optional[str]) -> dict:
    if not config.google_delegation_configured():
        return {"ok": False, "message": "Google delegation isn't configured (set GOOGLE_SERVICE_ACCOUNT_PATH)."}
    if not subject_email:
        return {"ok": False, "message": "No signed-in email to test delegated Gmail access with."}
    from bott.skills.connectors import gmail as gmail_mod

    gt = gmail_mod._impersonated(SimpleNamespace(user_id=subject_email))
    gt.search_emails("", 1)
    return {"ok": True, "message": f"Delegated Gmail read succeeded for {subject_email}."}


def _drive_probe(subject_email: Optional[str]) -> dict:
    if not config.google_delegation_configured():
        return {"ok": False, "message": "Google delegation isn't configured (set GOOGLE_SERVICE_ACCOUNT_PATH)."}
    if not subject_email:
        return {"ok": False, "message": "No signed-in email to test delegated Drive access with."}
    from bott.skills.connectors import drive as drive_mod

    gt = drive_mod._impersonated(SimpleNamespace(user_id=subject_email))
    gt.search_files("", 1)
    return {"ok": True, "message": f"Delegated Drive read succeeded for {subject_email}."}


def _calendar_probe(subject_email: Optional[str]) -> dict:
    if not config.google_delegation_configured():
        return {"ok": False, "message": "Google delegation isn't configured (set GOOGLE_SERVICE_ACCOUNT_PATH)."}
    if not subject_email:
        return {"ok": False, "message": "No signed-in email to test delegated Calendar access with."}
    from bott.skills.connectors import calendar as calendar_mod

    gt = calendar_mod._impersonated(SimpleNamespace(user_id=subject_email))
    gt.list_calendars()
    return {"ok": True, "message": f"Delegated Calendar read succeeded for {subject_email}."}


_GOOGLE_SERVICES: dict[str, Callable[[Optional[str]], dict]] = {
    "gmail": _gmail_probe,
    "drive": _drive_probe,
    "calendar": _calendar_probe,
}


def _google(subject_email: Optional[str]) -> dict:
    """The console's single 'Google' card runs all three delegated scopes and reports the
    combined result — a Workspace admin can misconfigure any one of them independently."""
    if not config.google_delegation_configured():
        return {"ok": False, "message": "Google delegation isn't configured (set GOOGLE_SERVICE_ACCOUNT_PATH)."}
    if not subject_email:
        return {"ok": False, "message": "No signed-in email to test Google delegation with."}
    parts: list[str] = []
    ok = True
    for kind, fn in _GOOGLE_SERVICES.items():
        try:
            result = fn(subject_email)
        except Exception as e:  # noqa: BLE001 — one scope failing shouldn't crash the others
            result = {"ok": False, "message": str(e).strip() or e.__class__.__name__}
        ok = ok and bool(result.get("ok"))
        parts.append(f"{kind}: {'ok' if result.get('ok') else result.get('message')}")
    return {"ok": ok, "message": "; ".join(parts)}


_PROBES: dict[str, Callable[[Optional[str]], dict]] = {
    "jira": lambda subject: _jira(),
    "confluence": lambda subject: _confluence(),
    "slack": lambda subject: _slack(),
    "memra": lambda subject: _memra(),
    "sentry": lambda subject: _sentry(),
    "codex": lambda subject: _codex(),
    "gmail": _gmail_probe,
    "drive": _drive_probe,
    "calendar": _calendar_probe,
    "google": _google,
}


def probe(name: str, subject_email: Optional[str] = None) -> dict:
    """Run one connector's live health check. Raises ``KeyError`` for an unknown name
    (the console router 404s on that); every known probe always returns a
    ``{"ok": bool, "message": str}`` dict, even when the round-trip itself blows up."""
    key = (name or "").strip().lower()
    if key not in _PROBES:
        raise KeyError(name)
    try:
        result = _PROBES[key](subject_email)
        return {"ok": bool(result.get("ok")), "message": str(result.get("message") or "")}
    except Exception as e:  # noqa: BLE001 — a probe must NEVER raise past this point
        log.warning("connector probe %r failed: %s", key, redact(str(e)))
        msg = str(e).strip() or e.__class__.__name__
        return {"ok": False, "message": f"Couldn't reach {key} ({msg})."}
