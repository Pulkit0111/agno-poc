"""Usage ledger for the shared org Codex account.

Every single one of Bott's LLM calls goes through one ChatGPT subscription — there was
previously no way for an admin to see usage trending toward a rate ceiling before it turned
into everyone getting 429'd at once. This is a health signal, not a billing meter: the
subscription has no per-token price, so `record_call` tracks request volume and (best-
effort) output tokens, not cost.
"""

from __future__ import annotations

import time
from typing import Optional

from sqlalchemy import text

from bott.shared.db import get_engine
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.codex_usage")


def record_call(user_id: Optional[str], model_id: str, output_tokens: int = 0) -> None:
    """Best-effort: a usage-recording failure must never break the model call it's
    recording — this is purely a visibility signal, not something correctness depends on."""
    try:
        with get_engine().begin() as c:
            c.execute(text(
                "INSERT INTO codex_usage (user_id, model_id, output_tokens, created) "
                "VALUES (:u, :m, :t, :c)"
            ), {"u": user_id, "m": model_id, "t": int(output_tokens or 0), "c": time.time()})
    except Exception as e:  # noqa: BLE001 — visibility must never break the thing it watches
        log.warning("codex usage recording failed: %s", e)


def usage_summary(window_s: int = 3600) -> dict:
    """Requests + output tokens in the last `window_s` seconds, plus who's driving the
    volume — enough for an admin to see a spike coming before it becomes an outage."""
    since = time.time() - window_s
    with get_engine().connect() as c:
        totals = c.execute(text(
            "SELECT COUNT(*), COALESCE(SUM(output_tokens), 0) FROM codex_usage "
            "WHERE created >= :since"
        ), {"since": since}).fetchone()
        by_user = c.execute(text(
            "SELECT COALESCE(user_id, '(unknown)') AS u, COUNT(*) AS n FROM codex_usage "
            "WHERE created >= :since GROUP BY u ORDER BY n DESC LIMIT 5"
        ), {"since": since}).fetchall()
    return {
        "window_s": window_s,
        "requests": int(totals[0] or 0) if totals else 0,
        "output_tokens": int(totals[1] or 0) if totals else 0,
        "top_users": [{"user_id": r[0], "requests": int(r[1])} for r in by_user],
    }
