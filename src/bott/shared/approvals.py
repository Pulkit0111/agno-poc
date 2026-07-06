"""Reusable approval gate. Any world-changing action records a request, surfaces
Approve/Dismiss in Slack, and blocks until decided. One primitive for PR-open,
self-authored-tool registration, client-facing sends, etc."""

from __future__ import annotations

import time

from sqlalchemy import text

from bott.shared.db import get_engine
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.approvals")


def init_approvals() -> None:
    from bott.shared.schema import init_schema
    init_schema()


def create_request(user_id: str, action: str, summary: str, payload: str | None = None) -> int:
    with get_engine().begin() as c:
        res = c.execute(text(
            "INSERT INTO approvals(user_id,action,summary,status,payload,created) "
            "VALUES (:u,:a,:s,'pending',:p,:t) RETURNING id"
        ), {"u": user_id, "a": action, "s": summary, "p": payload, "t": time.time()})
        return int(res.fetchone()[0])


def get_request(approval_id: int) -> dict | None:
    with get_engine().connect() as c:
        row = c.execute(text(
            "SELECT id,user_id,action,summary,status,decided_by,payload,created "
            "FROM approvals WHERE id=:id"
        ), {"id": approval_id}).fetchone()
        return dict(row._mapping) if row else None


def decide(approval_id: int, approved: bool, decided_by: str) -> None:
    with get_engine().begin() as c:
        res = c.execute(text(
            "UPDATE approvals SET status=:st, decided_by=:by "
            "WHERE id=:id AND status='pending'"
        ), {"st": "approved" if approved else "dismissed", "by": decided_by, "id": approval_id})
        if res.rowcount == 0:
            log.warning("approval %s not updated (not found or already decided)", approval_id)


def status(approval_id: int) -> str:
    with get_engine().begin() as c:
        row = c.execute(text("SELECT status FROM approvals WHERE id=:id"),
                        {"id": approval_id}).fetchone()
        return row[0] if row else "pending"


def wait_for_decision(approval_id: int, timeout: float, poll: float = 1.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = status(approval_id)
        if s != "pending":
            return s
        time.sleep(poll)
    return "pending"


def pending(limit: int = 8) -> list[dict]:
    """Return up to *limit* pending approvals, newest first (read-only)."""
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT id, action, summary, created FROM approvals "
            "WHERE status='pending' ORDER BY id DESC LIMIT :lim"
        ), {"lim": limit}).fetchall()
    return [{"id": int(r[0]), "action": r[1], "summary": r[2], "created": r[3]}
            for r in rows]


def pending_for(user_id: str, limit: int = 5) -> list[dict]:
    """Pending approvals THIS user requested, newest first — the App Home
    'Waiting on you' inbox (approval cards in threads scroll away; Home doesn't)."""
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT id, action, summary, created FROM approvals "
            "WHERE status='pending' AND user_id=:uid ORDER BY id DESC LIMIT :lim"
        ), {"uid": user_id, "lim": limit}).fetchall()
    return [{"id": int(r[0]), "action": r[1], "summary": r[2], "created": r[3]}
            for r in rows]


def pending_count() -> int:
    """Return the total number of pending approvals."""
    with get_engine().connect() as c:
        row = c.execute(text(
            "SELECT COUNT(*) FROM approvals WHERE status='pending'"
        )).fetchone()
    return int(row[0]) if row else 0


def pending_all(limit: int = 50) -> list[dict]:
    """All pending approvals with requester — the console admin view."""
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT id, user_id, action, summary, created FROM approvals "
            "WHERE status='pending' ORDER BY id DESC LIMIT :lim"
        ), {"lim": limit}).fetchall()
    return [{"id": int(r[0]), "user_id": r[1], "action": r[2], "summary": r[3],
             "created": r[4]} for r in rows]
