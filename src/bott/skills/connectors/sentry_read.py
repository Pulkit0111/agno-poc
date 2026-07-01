"""Read-only Sentry connector tools (org-credential). Shared org data — one token reads
the org's incidents for everyone; no per-user isolation applies (intended shared access)."""

from __future__ import annotations

from typing import Callable

from bott.shared import config
from bott.shared.integrations.sentry import SentryClient
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.connectors.sentry")

_NOT_CONFIGURED = "Sentry isn't configured (set SENTRY_ORG_SLUG, SENTRY_API_TOKEN)."


def _client() -> SentryClient:
    return SentryClient(
        base_url=config.sentry_base_url(),      # type: ignore[arg-type]
        org_slug=config.sentry_org_slug(),      # type: ignore[arg-type]
        api_token=config.sentry_api_token(),    # type: ignore[arg-type]
    )


def _fmt_issue(i: dict) -> str:
    bits = [i.get("shortId") or i.get("id", "?"), i.get("title", "")]
    meta = " · ".join(x for x in (i.get("level", ""), f"{i.get('count','')} events" if i.get("count") else "",
                                  i.get("status", ""), i.get("permalink", "")) if x)
    return f"- {' — '.join(b for b in bits if b)}" + (f"  ({meta})" if meta else "")


def sentry_list_issues(query: str = "is:unresolved", limit: int = 20) -> str:
    """List Sentry issues (read-only). `query` is Sentry search syntax (e.g. 'is:unresolved
    level:error'). Returns matching issues with shortId, title, level, event count, link."""
    if not config.sentry_configured():
        return _NOT_CONFIGURED
    try:
        issues = _client().list_issues(query, limit)
    except Exception as e:  # noqa: BLE001
        log.error("sentry list failed: %s", redact(str(e)))
        return "Couldn't reach Sentry right now."
    if not issues:
        return f"No Sentry issues matched '{query}'."
    return f"Sentry issues for '{query}':\n" + "\n".join(_fmt_issue(i) for i in issues)


def sentry_get_issue(issue_id: str) -> str:
    """Fetch one Sentry issue by id (read-only)."""
    if not config.sentry_configured():
        return _NOT_CONFIGURED
    try:
        i = _client().get_issue(issue_id)
    except Exception as e:  # noqa: BLE001
        log.error("sentry get failed: %s", redact(str(e)))
        return "Couldn't reach Sentry right now."
    return f"Sentry issue {i.get('shortId') or issue_id}:\n{_fmt_issue(i)}"


def sentry_issue_events(issue_id: str, limit: int = 5) -> str:
    """List recent events for a Sentry issue (read-only): release, environment, summary."""
    if not config.sentry_configured():
        return _NOT_CONFIGURED
    try:
        events = _client().issue_events(issue_id, limit)
    except Exception as e:  # noqa: BLE001
        log.error("sentry events failed: %s", redact(str(e)))
        return "Couldn't reach Sentry right now."
    if not events:
        return f"No recent events for Sentry issue {issue_id}."
    lines = [f"- {e.get('dateCreated','')} · {e.get('environment','')} · "
             f"{e.get('release','')} — {e.get('message','')}".rstrip(" ·—") for e in events]
    return f"Recent events for {issue_id}:\n" + "\n".join(lines)


def sentry_read_tools() -> list[Callable]:
    return ([sentry_list_issues, sentry_get_issue, sentry_issue_events]
            if config.sentry_configured() else [])
