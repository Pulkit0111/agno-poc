"""Curated engagement shortlist for the delivery-digest dropdown.

Memra has ~86 active engagements; dumping all of them is bad UX. We surface the ones
that need watching first — high/medium risk, then by risk score — capped to a sane list.
"""

from __future__ import annotations

from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.slack_home.engagements")

_BAND_ORDER = {"high": 0, "medium": 1, "low": 2}


def engagement_shortlist(limit: int = 20) -> list[dict]:
    """[{id, account, band}] sorted at-risk-first. Empty list if Memra is unreachable."""
    try:
        from bott.shared.context import MemraClient

        res = MemraClient().engagements_at_risk()
    except Exception as e:  # noqa: BLE001 — never let a Memra hiccup break the modal
        log.error("engagements_at_risk failed: %s", e)
        return []

    engs = (res or {}).get("engagements", []) if isinstance(res, dict) else []

    def sort_key(e: dict):
        band = (e.get("risk_band") or "").lower()
        return (_BAND_ORDER.get(band, 3), -(e.get("risk_score") or 0.0))

    out = []
    for e in sorted(engs, key=sort_key)[:limit]:
        eid = e.get("engagement_id")
        if not eid:
            continue
        out.append({
            "id": eid,
            "account": e.get("account") or eid,
            "band": (e.get("risk_band") or "unknown"),
        })
    return out


def sprint_board_options_with_reason(limit: int = 50) -> tuple[list[tuple[str, str]], str | None]:
    """([(label, project_key)], reason). ``reason`` is None on success, else a human message
    explaining WHY the list is empty — so the modal never shows a misleading 'no boards found'
    when the real cause is missing creds or an auth error."""
    from bott.shared import config

    if not config.jira_configured():
        return [], ("Jira isn't configured. Set JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN "
                    "in .env and restart the app.")
    try:
        from bott.skills.sprint_report.tool import _jira

        boards = _jira().list_boards()
    except Exception as e:  # noqa: BLE001 — never let a Jira hiccup break the modal
        log.error("list_boards failed: %s", e)
        return [], f"Couldn't reach Jira: {e}"

    # Only Scrum boards have sprints, so only they can produce a sprint report. Dedup by
    # project key (a project may have several boards) so each engagement appears once.
    opts: list[tuple[str, str]] = []
    seen: set[str] = set()
    for b in sorted(boards, key=lambda x: (x.get("project_name") or x.get("name") or "")):
        if b.get("type") != "scrum":
            continue
        key = (b.get("project_key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        name = b.get("project_name") or b.get("name") or key
        opts.append((f"{key} — {name}", key))
    if not opts:
        return [], ("Connected to Jira, but no Scrum boards are visible to this account. "
                    "Sprint reports need a Scrum board with sprints (Kanban boards have none).")
    return opts[:limit], None


def sprint_board_options(limit: int = 50) -> list[tuple[str, str]]:
    """[(label, project_key)] for the sprint-report dropdown (just the options)."""
    return sprint_board_options_with_reason(limit)[0]
