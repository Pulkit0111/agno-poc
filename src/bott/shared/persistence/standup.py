"""Standup (DSM) collection state — the async pre-read for the redesigned DSM flow.

A standup "round" is keyed by (team, date). When the open trigger fires it records the
channel + the thread-root message ts; people's form submissions are stored against that
round; the pre-read and post-call triggers read them back and reply in that thread.

Uses the same shared engine (Postgres in prod, SQLite in dev) as every other foundation
table — get_engine(), not a private file. This used to open its own raw sqlite3 file
(REVIEW_DB_PATH) that ignored DATABASE_URL entirely: in production that meant standup state
was written to local disk instead of the shared database — lost if the container was
recreated, and invisible to any other replica under a multi-instance deployment (one
instance's `open_standup` and another's scheduled `close_standup` could land on different
machines and never see each other's state).
"""

from __future__ import annotations

import time
from typing import Optional

from sqlalchemy import text

from bott.shared.db import get_engine


def init_db() -> None:
    from bott.shared.schema import init_schema
    init_schema()


def open_round(team: str, date: str, channel: str, thread_ts: str) -> None:
    """Record (or reset) the open round for a team+date with its thread root."""
    init_db()
    with get_engine().begin() as c:
        c.execute(text(
            "INSERT INTO standup_rounds(team, date, channel, thread_ts, created) "
            "VALUES (:team, :date, :channel, :thread_ts, :created) "
            "ON CONFLICT(team, date) DO UPDATE SET channel=excluded.channel, "
            "thread_ts=excluded.thread_ts, created=excluded.created"
        ), {"team": team, "date": date, "channel": channel, "thread_ts": thread_ts,
            "created": time.time()})


def get_round(team: str, date: str) -> Optional[dict]:
    init_db()
    with get_engine().connect() as c:
        row = c.execute(text(
            "SELECT channel, thread_ts FROM standup_rounds WHERE team=:team AND date=:date"
        ), {"team": team, "date": date}).fetchone()
        return {"channel": row[0], "thread_ts": row[1]} if row else None


def add_response(team: str, date: str, user: str, yesterday: str, today: str,
                 blockers: str) -> None:
    init_db()
    with get_engine().begin() as c:
        c.execute(text(
            "INSERT INTO standup_responses(team, date, user_id, yesterday, today, "
            "blockers, created) VALUES (:team, :date, :user, :yesterday, :today, "
            ":blockers, :created)"
        ), {"team": team, "date": date, "user": user, "yesterday": yesterday,
            "today": today, "blockers": blockers, "created": time.time()})


def responses(team: str, date: str) -> list[dict]:
    init_db()
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT user_id, yesterday, today, blockers FROM standup_responses "
            "WHERE team=:team AND date=:date ORDER BY id"
        ), {"team": team, "date": date}).fetchall()
        return [{"user": r[0], "yesterday": r[1], "today": r[2], "blockers": r[3]}
                for r in rows]
