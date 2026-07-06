"""Postgres-backed non-queue persistence: settings KV, webhook/commit dedup, review traces.

All six functions mirror the semantics of the corresponding store.py functions but use
get_engine() + SQLAlchemy text DML instead of raw sqlite3, making them work on both
Postgres (production) and SQLite (tests).
"""

from __future__ import annotations

import time
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from bott.shared.db import get_engine
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.persistence.records")


# ---------------------------------------------------------------------------
# Settings KV
# ---------------------------------------------------------------------------

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Read a shared setting. Tolerant: returns ``default`` on any error or missing row."""
    try:
        with get_engine().begin() as c:
            row = c.execute(
                text("SELECT value FROM settings WHERE key = :k"),
                {"k": key},
            ).fetchone()
            return row[0] if row else default
    except Exception:  # noqa: BLE001 — table absent, DB unreachable, etc.
        return default


def set_setting(key: str, value: str) -> None:
    """Upsert a setting. Uses INSERT … ON CONFLICT which works on both Postgres and
    SQLite 3.24+ (the minimum shipped with Python 3.12)."""
    with get_engine().begin() as c:
        c.execute(
            text(
                "INSERT INTO settings(key, value) VALUES (:k, :v) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
            ),
            {"k": key, "v": value},
        )


def list_settings_by_prefix(prefix: str) -> dict[str, str]:
    """All settings whose key starts with prefix, as {key: value}. Full-scan — the settings
    table has no secondary index, but it's small (KV config, not event data)."""
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT key, value FROM settings WHERE key LIKE :p"
        ), {"p": f"{prefix}%"}).fetchall()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# Webhook / commit dedup
# ---------------------------------------------------------------------------

def seen_delivery(delivery_id: str) -> bool:
    """Record a GitHub webhook delivery id; return True if already seen (dedup)."""
    if not delivery_id:
        return False
    try:
        with get_engine().begin() as c:
            c.execute(
                text(
                    "INSERT INTO github_deliveries(delivery_id, created) "
                    "VALUES (:d, :t)"
                ),
                {"d": delivery_id, "t": time.time()},
            )
        return False
    except IntegrityError:
        return True


def seen_commit(owner: str, name: str, sha: str) -> bool:
    """Record an (owner/name, head-SHA) pair; return True if already reviewed (dedup)."""
    if not (owner and name and sha):
        return False
    key = f"{owner}/{name}@{sha}".lower()
    try:
        with get_engine().begin() as c:
            c.execute(
                text(
                    "INSERT INTO reviewed_commits(repo_sha, created) "
                    "VALUES (:k, :t)"
                ),
                {"k": key, "t": time.time()},
            )
        return False
    except IntegrityError:
        return True


# ---------------------------------------------------------------------------
# Review traces
# ---------------------------------------------------------------------------

def _is_postgres() -> bool:
    return get_engine().url.get_backend_name().startswith("postgre")


def save_trace(
    *,
    channel: str,
    thread_ts: str,
    owner: str,
    name: str,
    pr_number: int,
    original_verdict: str,
    final_verdict: str,
    output_json: str,
    gate_json: str,
) -> int:
    """Insert a review trace and return the new row id."""
    params = {
        "ch": channel,
        "ts": thread_ts,
        "ow": owner,
        "nm": name,
        "pr": pr_number,
        "ov": original_verdict,
        "fv": final_verdict,
        "oj": output_json,
        "gj": gate_json,
        "cr": time.time(),
    }
    sql = (
        "INSERT INTO review_traces"
        "(channel, thread_ts, owner, name, pr_number, "
        "original_verdict, final_verdict, output_json, gate_json, created) "
        "VALUES (:ch, :ts, :ow, :nm, :pr, :ov, :fv, :oj, :gj, :cr)"
    )
    if _is_postgres():
        sql += " RETURNING id"
        with get_engine().begin() as c:
            res = c.execute(text(sql), params)
            return int(res.fetchone()[0])
    else:
        with get_engine().begin() as c:
            res = c.execute(text(sql), params)
            return int(res.lastrowid)


def latest_trace_for_thread(channel: str, thread_ts: str) -> Optional[dict]:
    """Return the newest review trace for a Slack thread, or None."""
    with get_engine().begin() as c:
        row = c.execute(
            text(
                "SELECT id, channel, thread_ts, owner, name, pr_number, "
                "original_verdict, final_verdict, output_json, gate_json, created "
                "FROM review_traces "
                "WHERE channel = :ch AND thread_ts = :ts "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"ch": channel, "ts": thread_ts},
        ).fetchone()
    if row is None:
        return None
    keys = ("id", "channel", "thread_ts", "owner", "name", "pr_number",
            "original_verdict", "final_verdict", "output_json", "gate_json", "created")
    return dict(zip(keys, row))


def trace_stats(since_epoch: Optional[float] = None) -> dict:
    """Aggregate descriptive statistics over review_traces.

    These are raw counts over stored trace rows — not quality or accuracy metrics.
    There are no ground-truth labels, so terms like false-positive rate or
    missed-blocker rate are not computable from this data.

    Args:
        since_epoch: If provided, only rows with created >= since_epoch are counted.

    Returns a dict with:
        total          — int total row count in the window
        by_verdict     — {final_verdict: count} mapping
        by_repo        — [(\"owner/name\", count), ...] sorted descending, top 10
        rereview_changed — count of rows where original_verdict IS NOT NULL
                           and original_verdict != final_verdict
        by_week        — {\"YYYY-Www\": count} bucket map (ISO week of epoch)
    """
    import datetime

    params: dict = {}
    where = ""
    if since_epoch is not None:
        where = "WHERE created >= :since"
        params["since"] = since_epoch

    with get_engine().begin() as c:
        # Total count
        total_row = c.execute(
            text(f"SELECT COUNT(*) FROM review_traces {where}"),  # noqa: S608
            params,
        ).fetchone()
        total: int = int(total_row[0]) if total_row else 0

        # By final_verdict
        verdict_rows = c.execute(
            text(
                f"SELECT final_verdict, COUNT(*) AS cnt "  # noqa: S608
                f"FROM review_traces {where} "
                f"GROUP BY final_verdict "
                f"ORDER BY cnt DESC"
            ),
            params,
        ).fetchall()
        by_verdict: dict[str, int] = {
            (row[0] or "unknown"): int(row[1]) for row in verdict_rows
        }

        # By repo (owner/name)
        repo_rows = c.execute(
            text(
                f"SELECT owner, name, COUNT(*) AS cnt "  # noqa: S608
                f"FROM review_traces {where} "
                f"GROUP BY owner, name "
                f"ORDER BY cnt DESC "
                f"LIMIT 10"
            ),
            params,
        ).fetchall()
        by_repo: list[tuple[str, int]] = [
            (f"{row[0] or ''}/{row[1] or ''}", int(row[2])) for row in repo_rows
        ]

        # Re-review changed verdict count
        rereview_where = (
            f"{where} AND " if where else "WHERE "
        )
        changed_row = c.execute(
            text(
                f"SELECT COUNT(*) FROM review_traces "  # noqa: S608
                f"{rereview_where}"
                f"original_verdict IS NOT NULL "
                f"AND original_verdict != final_verdict"
            ),
            params,
        ).fetchone()
        rereview_changed: int = int(changed_row[0]) if changed_row else 0

        # All created timestamps for bucketing by week
        ts_rows = c.execute(
            text(f"SELECT created FROM review_traces {where}"),  # noqa: S608
            params,
        ).fetchall()

    # Bucket into ISO weeks client-side (avoids DB-dialect strftime differences)
    by_week: dict[str, int] = {}
    for (ts,) in ts_rows:
        if ts is not None:
            dt = datetime.datetime.fromtimestamp(float(ts), tz=datetime.timezone.utc)
            week_key = dt.strftime("%G-W%V")  # ISO year + ISO week, e.g. "2026-W27"
            by_week[week_key] = by_week.get(week_key, 0) + 1

    return {
        "total": total,
        "by_verdict": by_verdict,
        "by_repo": by_repo,
        "rereview_changed": rereview_changed,
        "by_week": dict(sorted(by_week.items())),
    }
