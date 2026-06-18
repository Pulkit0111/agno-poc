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
