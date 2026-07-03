"""Read-only Jira connector tools (general search + get an issue), reusing the JiraClient
that already powers sprint reports. Shared org data — one bot identity reads it."""

from __future__ import annotations

from typing import Callable

from bott.shared import config
from bott.shared.integrations.jira import JiraClient
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.connectors.jira")


def _client() -> JiraClient:
    return JiraClient(
        base_url=config.jira_base_url(),  # type: ignore[arg-type]
        email=config.jira_email(),  # type: ignore[arg-type]
        api_token=config.jira_api_token(),  # type: ignore[arg-type]
        story_points_field=config.jira_story_points_field(),
    )


def _fmt(i: dict, base: str) -> str:
    url = f"{base}/browse/{i['key']}" if base and i.get("key") else ""
    bits = [i.get("key", "?"), i.get("summary", "")]
    meta = " · ".join(x for x in (i.get("status", ""), i.get("issue_type", ""), url) if x)
    return f"- {' — '.join(b for b in bits if b)}" + (f"  ({meta})" if meta else "")


def jira_search(query: str, limit: int = 15) -> str:
    """Search Jira issues by free text or JQL (read-only). Returns matching issues with key,
    summary, status, type, and link — use them to answer or compose.

    Args:
        query: Free text (e.g. 'login bug in PADI') or a JQL string.
        limit: Max issues (default 15).
    """
    if not config.jira_configured():
        return "Jira isn't configured (set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)."
    try:
        c = _client()
        issues = c.search_issues(query, limit)
    except Exception as e:  # noqa: BLE001
        log.error("jira search failed: %s", e)
        return f"Couldn't search Jira ({e})."
    if not issues:
        return f"No Jira issues matched '{query}'."
    return f"Jira issues for '{query}':\n" + "\n".join(_fmt(i, c.base_url) for i in issues)


def _fmt_detail(d: dict, base: str) -> str:
    url = f"{base}/browse/{d['key']}" if base and d.get("key") else ""
    lines = [f"*{d.get('key', '?')}* — {d.get('summary', '')}"]
    meta = " · ".join(x for x in (
        d.get("status", ""), d.get("issue_type", ""),
        f"Priority: {d['priority']}" if d.get("priority") else "") if x)
    if meta:
        lines.append(meta)
    who = " · ".join(x for x in (
        f"Assignee: {d['assignee']}" if d.get("assignee") else "",
        f"Reporter: {d['reporter']}" if d.get("reporter") else "") if x)
    if who:
        lines.append(who)
    if d.get("updated"):
        lines.append(f"Updated: {d['updated'][:10]}")
    desc = (d.get("description") or "").strip()
    lines.append("\n" + (desc[:800] + ("…" if len(desc) > 800 else "")) if desc
                 else "\n_No description on the ticket._")
    if d.get("comment_count"):
        lines.append(f"{d['comment_count']} comment(s) on the ticket.")
    if url:
        lines.append(url)
    return "\n".join(lines)


def get_jira_issue(key: str) -> str:
    """Fetch one Jira issue by key (e.g. 'PADI-123') with full detail — description, status,
    priority, assignee, reporter — read-only.

    Args:
        key: The Jira issue key.
    """
    if not config.jira_configured():
        return "Jira isn't configured (set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)."
    try:
        c = _client()
        return f"Jira {key}:\n" + _fmt_detail(c.get_issue_detail(key), c.base_url)
    except Exception as e:  # noqa: BLE001
        log.error("jira get_issue failed: %s", e)
        return f"Couldn't fetch Jira issue '{key}' ({e})."


def jira_read_tools() -> list[Callable]:
    return [jira_search, get_jira_issue] if config.jira_configured() else []
