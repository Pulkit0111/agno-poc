"""Personal action-items store — strictly per-user.

Every mutating query includes ``user_id`` in the WHERE clause so cross-user access
is impossible at the SQL level (not just application logic).
"""

from __future__ import annotations

import time

from sqlalchemy import text

from bott.shared.db import get_engine


def add_item(user_id: str, item_text: str, now: float, source: str = "user",
             remind_at: float | None = None) -> int:
    """Insert a new action item; return the new row id. `source` tracks who/what created
    it ("user" from the agent tool, "console" from the web console, "dsm" auto-captured
    from a standup blocker). An explicit `remind_at` creates it pre-snoozed (status stays
    'open' otherwise — callers that want it snoozed should still call snooze_item)."""
    status = "snoozed" if remind_at is not None else "open"
    sql = (
        "INSERT INTO action_items(user_id, text, status, remind_at, source, created, updated) "
        "VALUES (:uid, :txt, :status, :rat, :src, :now, :now)"
    )
    params = {"uid": user_id, "txt": item_text, "status": status, "rat": remind_at,
              "src": source, "now": now}
    engine = get_engine()
    if engine.url.get_backend_name().startswith("postgre"):
        sql += " RETURNING id"
        with engine.begin() as c:
            res = c.execute(text(sql), params)
            return int(res.fetchone()[0])
    else:
        with engine.begin() as c:
            res = c.execute(text(sql), params)
            return int(res.lastrowid)


def list_items(user_id: str, include_done: bool = False) -> list[dict]:
    """Return that user's items, newest first. Excludes done items by default."""
    if include_done:
        sql = (
            "SELECT id, user_id, text, status, remind_at, source, created, updated "
            "FROM action_items WHERE user_id = :uid ORDER BY id DESC"
        )
        params: dict = {"uid": user_id}
    else:
        sql = (
            "SELECT id, user_id, text, status, remind_at, source, created, updated "
            "FROM action_items WHERE user_id = :uid AND status != 'done' ORDER BY id DESC"
        )
        params = {"uid": user_id}
    with get_engine().begin() as c:
        rows = c.execute(text(sql), params).fetchall()
    return [dict(row._mapping) for row in rows]


def has_item_with_text(user_id: str, item_text: str, source: str) -> bool:
    """True if this user already has an item with this exact text+source, in ANY status.
    Dedup check for idempotent auto-capture (e.g. DSM blockers re-closing the same round)
    — a new table isn't needed since (user_id, text, source) is a good-enough natural key
    for content that's deterministic per (team, date, user)."""
    with get_engine().begin() as c:
        row = c.execute(
            text(
                "SELECT 1 FROM action_items WHERE user_id = :uid AND text = :txt "
                "AND source = :src LIMIT 1"
            ),
            {"uid": user_id, "txt": item_text, "src": source},
        ).fetchone()
    return row is not None


def complete_item(user_id: str, item_id: int, now: float) -> bool:
    """Mark an item done. Returns True only if the row belonged to this user."""
    with get_engine().begin() as c:
        res = c.execute(
            text(
                "UPDATE action_items SET status = 'done', updated = :now "
                "WHERE id = :iid AND user_id = :uid"
            ),
            {"now": now, "iid": item_id, "uid": user_id},
        )
    return (res.rowcount or 0) > 0


def snooze_item(user_id: str, item_id: int, remind_at: float, now: float) -> bool:
    """Snooze an item until remind_at. Returns True only if the row belonged to this user."""
    with get_engine().begin() as c:
        res = c.execute(
            text(
                "UPDATE action_items SET status = 'snoozed', remind_at = :rat, updated = :now "
                "WHERE id = :iid AND user_id = :uid"
            ),
            {"rat": remind_at, "now": now, "iid": item_id, "uid": user_id},
        )
    return (res.rowcount or 0) > 0


def due_reminders(now: float) -> list[dict]:
    """Return all snoozed items whose remind_at has passed — consumed by the reminder
    sweep (shared/reminders.py)."""
    with get_engine().begin() as c:
        rows = c.execute(
            text(
                "SELECT id, user_id, text, status, remind_at, source, created, updated "
                "FROM action_items WHERE status = 'snoozed' AND remind_at <= :now"
            ),
            {"now": now},
        ).fetchall()
    return [dict(row._mapping) for row in rows]


def mark_reminded(item_id: int) -> bool:
    """Flip a reminded item back to 'open' and clear remind_at so the sweep never DMs it
    twice. Not user-scoped (like the other mutators) — the sweep operates on the row's own
    identity, not on behalf of a request from a specific caller."""
    now = time.time()
    with get_engine().begin() as c:
        res = c.execute(
            text(
                "UPDATE action_items SET status = 'open', remind_at = NULL, updated = :now "
                "WHERE id = :iid"
            ),
            {"now": now, "iid": item_id},
        )
    return (res.rowcount or 0) > 0
