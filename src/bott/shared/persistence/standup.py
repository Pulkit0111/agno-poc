"""Standup (DSM) collection state — the async pre-read for the redesigned DSM flow.

A standup "round" is keyed by (team, date). When the open trigger fires it records the
channel + the thread-root message ts; people's form submissions are stored against that
round; the pre-read and post-call triggers read them back and reply in that thread.

Shares the worker DB (REVIEW_DB_PATH) — this is operational state, not user memory.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional

from ..config import db_path

_lock = threading.Lock()


def _conn(db_file: Optional[str] = None) -> sqlite3.Connection:
    c = sqlite3.connect(db_file or db_path(), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db(db_file: Optional[str] = None) -> None:
    with _conn(db_file) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS standup_rounds (
                team TEXT NOT NULL, date TEXT NOT NULL,
                channel TEXT NOT NULL, thread_ts TEXT NOT NULL,
                created REAL NOT NULL,
                PRIMARY KEY (team, date)
            );
            CREATE TABLE IF NOT EXISTS standup_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team TEXT NOT NULL, date TEXT NOT NULL, user TEXT NOT NULL,
                yesterday TEXT, today TEXT, blockers TEXT,
                created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_standup_resp ON standup_responses(team, date, id);
            """
        )


def open_round(team: str, date: str, channel: str, thread_ts: str, db_file: Optional[str] = None) -> None:
    """Record (or reset) the open round for a team+date with its thread root."""
    init_db(db_file)
    with _lock, _conn(db_file) as c:
        c.execute(
            "INSERT INTO standup_rounds(team, date, channel, thread_ts, created) VALUES (?,?,?,?,?) "
            "ON CONFLICT(team, date) DO UPDATE SET channel=excluded.channel, "
            "thread_ts=excluded.thread_ts, created=excluded.created",
            (team, date, channel, thread_ts, time.time()),
        )


def get_round(team: str, date: str, db_file: Optional[str] = None) -> Optional[dict]:
    init_db(db_file)
    with _conn(db_file) as c:
        row = c.execute(
            "SELECT channel, thread_ts FROM standup_rounds WHERE team=? AND date=?", (team, date)
        ).fetchone()
        return dict(row) if row else None


def add_response(team: str, date: str, user: str, yesterday: str, today: str,
                 blockers: str, db_file: Optional[str] = None) -> None:
    init_db(db_file)
    with _lock, _conn(db_file) as c:
        c.execute(
            "INSERT INTO standup_responses(team, date, user, yesterday, today, blockers, created) "
            "VALUES (?,?,?,?,?,?,?)",
            (team, date, user, yesterday, today, blockers, time.time()),
        )


def responses(team: str, date: str, db_file: Optional[str] = None) -> list[dict]:
    init_db(db_file)
    with _conn(db_file) as c:
        rows = c.execute(
            "SELECT user, yesterday, today, blockers FROM standup_responses "
            "WHERE team=? AND date=? ORDER BY id",
            (team, date),
        ).fetchall()
        return [dict(r) for r in rows]
