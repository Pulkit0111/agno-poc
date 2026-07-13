"""Personal action-items store — strictly per-user.

Every mutating query includes ``user_id`` in the WHERE clause so cross-user access
is impossible at the SQL level (not just application logic).
"""

from __future__ import annotations

import time

from sqlalchemy import text

from bott.shared.db import get_engine


def _is_postgres() -> bool:
    return get_engine().url.get_backend_name().startswith("postgre")


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
    if _is_postgres():
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


def claim_due_reminders(now: float) -> list[dict]:
    """Atomically CLAIM every due snoozed item: select + flip back to 'open' with
    remind_at cleared in ONE transaction, returning the claimed rows. Same
    multi-replica-safe shape as queue.claim_one — `FOR UPDATE SKIP LOCKED` on Postgres so
    two replicas sweeping concurrently can never both claim (and double-DM) the same item;
    plain SELECT on SQLite (single-writer, dev/tests only), exactly like queue.py.
    Callers DM *after* the claim; a failed DM should resnooze_item() to retry later."""
    skip = "FOR UPDATE SKIP LOCKED" if _is_postgres() else ""
    with get_engine().begin() as c:
        rows = c.execute(
            text(
                f"SELECT id, user_id, text, status, remind_at, source, created, updated "
                f"FROM action_items WHERE status = 'snoozed' AND remind_at <= :now {skip}"
            ),
            {"now": now},
        ).fetchall()
        items = [dict(row._mapping) for row in rows]
        for it in items:
            c.execute(
                text(
                    "UPDATE action_items SET status = 'open', remind_at = NULL, "
                    "updated = :now WHERE id = :iid"
                ),
                {"now": now, "iid": it["id"]},
            )
    return items


def resnooze_item(item_id: int, remind_at: float) -> bool:
    """Put a claimed item back to 'snoozed' with a fresh remind_at — the sweep's undo when
    a DM fails after claim_due_reminders already flipped the row, so the reminder retries
    instead of being silently lost. Not user-scoped for the same reason as mark_reminded."""
    now = time.time()
    with get_engine().begin() as c:
        res = c.execute(
            text(
                "UPDATE action_items SET status = 'snoozed', remind_at = :rat, "
                "updated = :now WHERE id = :iid"
            ),
            {"rat": remind_at, "now": now, "iid": item_id},
        )
    return (res.rowcount or 0) > 0


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
