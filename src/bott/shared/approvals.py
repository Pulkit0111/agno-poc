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


def create_request(user_id: str, action: str, summary: str) -> int:
    with get_engine().begin() as c:
        res = c.execute(text(
            "INSERT INTO approvals(user_id,action,summary,status,created) "
            "VALUES (:u,:a,:s,'pending',:t) RETURNING id"
        ), {"u": user_id, "a": action, "s": summary, "t": time.time()})
        return int(res.fetchone()[0])


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
