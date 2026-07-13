"""Personal, console-only quick checklist — strictly per-user.

Deliberately dumb: no Slack surface, no agent tools, no reminders, no admin variants.
Distinct from action_items.py (which syncs to Slack App Home and gets DM reminders).

Every mutating query includes ``user_id`` in the WHERE clause so cross-user access is
impossible at the SQL level (not just application logic) — mirrors action_items.py.
"""

from __future__ import annotations

import time

from sqlalchemy import text

from bott.shared.db import get_engine


def _is_postgres() -> bool:
    return get_engine().url.get_backend_name().startswith("postgre")


def add(user_id: str, item_text: str) -> int:
    """Insert a new todo; return the new row id."""
    now = time.time()
    sql = (
        "INSERT INTO todos(user_id, text, done, created, updated) "
        "VALUES (:uid, :txt, 0, :now, :now)"
    )
    params = {"uid": user_id, "txt": item_text, "now": now}
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


def list_for(user_id: str) -> list[dict]:
    """Return that user's todos, newest first."""
    with get_engine().begin() as c:
        rows = c.execute(
            text(
                "SELECT id, user_id, text, done, created, updated "
                "FROM todos WHERE user_id = :uid ORDER BY id DESC"
            ),
            {"uid": user_id},
        ).fetchall()
    return [dict(row._mapping) for row in rows]


def set_done(user_id: str, todo_id: int, done: bool) -> bool:
    """Flip a todo's done state. Returns True only if the row belonged to this user."""
    with get_engine().begin() as c:
        res = c.execute(
            text(
                "UPDATE todos SET done = :done, updated = :now "
                "WHERE id = :tid AND user_id = :uid"
            ),
            {"done": 1 if done else 0, "now": time.time(), "tid": todo_id, "uid": user_id},
        )
    return (res.rowcount or 0) > 0


def delete(user_id: str, todo_id: int) -> bool:
    """Delete a todo. Returns True only if the row belonged to this user."""
    with get_engine().begin() as c:
        res = c.execute(
            text("DELETE FROM todos WHERE id = :tid AND user_id = :uid"),
            {"tid": todo_id, "uid": user_id},
        )
    return (res.rowcount or 0) > 0


def clear_done(user_id: str) -> int:
    """Delete all of this user's done todos. Returns the number removed."""
    with get_engine().begin() as c:
        res = c.execute(
            text("DELETE FROM todos WHERE user_id = :uid AND done = 1"),
            {"uid": user_id},
        )
    return res.rowcount or 0
