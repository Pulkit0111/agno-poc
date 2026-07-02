"""Personal action-items store — strictly per-user.

Every mutating query includes ``user_id`` in the WHERE clause so cross-user access
is impossible at the SQL level (not just application logic).
"""

from __future__ import annotations

from sqlalchemy import text

from bott.shared.db import get_engine


def add_item(user_id: str, item_text: str, now: float) -> int:
    """Insert a new open action item; return the new row id."""
    sql = (
        "INSERT INTO action_items(user_id, text, status, created, updated) "
        "VALUES (:uid, :txt, 'open', :now, :now)"
    )
    engine = get_engine()
    if engine.url.get_backend_name().startswith("postgre"):
        sql += " RETURNING id"
        with engine.begin() as c:
            res = c.execute(text(sql), {"uid": user_id, "txt": item_text, "now": now})
            return int(res.fetchone()[0])
    else:
        with engine.begin() as c:
            res = c.execute(text(sql), {"uid": user_id, "txt": item_text, "now": now})
            return int(res.lastrowid)


def list_items(user_id: str, include_done: bool = False) -> list[dict]:
    """Return that user's items, newest first. Excludes done items by default."""
    if include_done:
        sql = (
            "SELECT id, user_id, text, status, remind_at, created, updated "
            "FROM action_items WHERE user_id = :uid ORDER BY id DESC"
        )
        params: dict = {"uid": user_id}
    else:
        sql = (
            "SELECT id, user_id, text, status, remind_at, created, updated "
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
    """Return all snoozed items whose remind_at has passed — for a future reminder sweep."""
    with get_engine().begin() as c:
        rows = c.execute(
            text(
                "SELECT id, user_id, text, status, remind_at, created, updated "
                "FROM action_items WHERE status = 'snoozed' AND remind_at <= :now"
            ),
            {"now": now},
        ).fetchall()
    return [dict(row._mapping) for row in rows]
