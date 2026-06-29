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
