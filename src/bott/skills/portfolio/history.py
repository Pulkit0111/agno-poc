"""Weekly portfolio snapshots, so trend-over-time charts accrue.

Memra exposes only a current-week snapshot, so we persist one summary point per run (in the
shared settings KV as a JSON list) and read them back for the dashboard's trend lines. One
point per date (upsert), capped to ~6 months."""

from __future__ import annotations

import json

from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.skills.portfolio.history")

_KEY = "portfolio_history"
_CAP = 26  # weeks retained


def load_history() -> list[dict]:
    """Past portfolio snapshot points, oldest-first. Empty list on any error."""
    try:
        from bott.shared.persistence import records

        raw = records.get_setting(_KEY)
        data = json.loads(raw) if raw else []
        return data if isinstance(data, list) else []
    except Exception as e:  # noqa: BLE001 — history is best-effort
        log.warning("load portfolio history failed: %s", e)
        return []


def record_snapshot(date_str: str, point: dict) -> list[dict]:
    """Upsert one snapshot point for ``date_str`` and return the full (capped) history."""
    hist = [h for h in load_history() if h.get("date") != date_str]
    hist.append({"date": date_str, **point})
    hist.sort(key=lambda h: h.get("date", ""))
    hist = hist[-_CAP:]
    try:
        from bott.shared.persistence import records

        records.set_setting(_KEY, json.dumps(hist))
    except Exception as e:  # noqa: BLE001 — never fail the dashboard over persistence
        log.warning("record portfolio history failed: %s", e)
    return hist
