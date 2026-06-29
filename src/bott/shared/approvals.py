"""Reusable approval gate. Any world-changing action records a request, surfaces
Approve/Dismiss in Slack, and blocks until decided. One primitive for PR-open,
self-authored-tool registration, client-facing sends, etc."""

from __future__ import annotations

import time

from sqlalchemy import text

from bott.shared.db import get_engine


def init_approvals() -> None:
    pk = "SERIAL PRIMARY KEY" if get_engine().url.get_backend_name().startswith("postgre") else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with get_engine().begin() as c:
        c.execute(text(f"""
            CREATE TABLE IF NOT EXISTS approvals (
                id {pk},
                user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                decided_by TEXT,
                created DOUBLE PRECISION NOT NULL
            )
        """))


def create_request(user_id: str, action: str, summary: str) -> int:
    with get_engine().begin() as c:
        res = c.execute(text(
            "INSERT INTO approvals(user_id,action,summary,status,created) "
            "VALUES (:u,:a,:s,'pending',:t) RETURNING id"
        ), {"u": user_id, "a": action, "s": summary, "t": time.time()})
        return int(res.fetchone()[0])


def decide(approval_id: int, approved: bool, decided_by: str) -> None:
    with get_engine().begin() as c:
        c.execute(text(
            "UPDATE approvals SET status=:st, decided_by=:by WHERE id=:id"
        ), {"st": "approved" if approved else "dismissed", "by": decided_by, "id": approval_id})


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
