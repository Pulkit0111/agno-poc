"""SQLite-backed task queue + review trace store + thread index.

Mirrors Bott's queue->worker->dispatch shape, scoped to the POC. The queue gives
crash-visibility and serializes reviews; traces persist each review's output so a
thread reply can drive an evidence-bound re-review.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..config import db_path

DB_FILE = db_path()  # env-overridable (REVIEW_DB_PATH); default preserves prior location
_lock = threading.Lock()


def _conn(db_file: Optional[str] = None) -> sqlite3.Connection:
    c = sqlite3.connect(db_file or DB_FILE, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db(db_file: Optional[str] = None) -> None:
    with _conn(db_file) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                args TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created REAL NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT, thread_ts TEXT,
                owner TEXT, name TEXT, pr_number INTEGER,
                original_verdict TEXT, final_verdict TEXT,
                output_json TEXT, gate_json TEXT,
                created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_traces_thread ON traces(channel, thread_ts, id);
            CREATE TABLE IF NOT EXISTS github_deliveries (
                delivery_id TEXT PRIMARY KEY,
                created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviewed_commits (
                repo_sha TEXT PRIMARY KEY,
                created REAL NOT NULL
            );
            """
        )
        # Migration: add attempts column to existing DBs.
        try:
            c.execute("ALTER TABLE tasks ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # already present


def seen_delivery(delivery_id: str, db_file: Optional[str] = None) -> bool:
    """Record a GitHub webhook delivery id; return True if already seen (dedup)."""
    if not delivery_id:
        return False
    with _lock, _conn(db_file) as c:
        try:
            c.execute(
                "INSERT INTO github_deliveries(delivery_id, created) VALUES (?,?)",
                (delivery_id, time.time()),
            )
            return False
        except sqlite3.IntegrityError:
            return True


def seen_commit(owner: str, name: str, sha: str, db_file: Optional[str] = None) -> bool:
    """Record an (owner/name, head-SHA) pair; return True if this exact commit was already
    reviewed (dedup). Stops rapid repeated `synchronize` events re-reviewing one commit."""
    if not (owner and name and sha):
        return False
    key = f"{owner}/{name}@{sha}".lower()
    with _lock, _conn(db_file) as c:
        try:
            c.execute(
                "INSERT INTO reviewed_commits(repo_sha, created) VALUES (?,?)",
                (key, time.time()),
            )
            return False
        except sqlite3.IntegrityError:
            return True


def recover_orphans(db_file: Optional[str] = None) -> int:
    """Mark any 'running' task as failed — it was interrupted by a restart.
    Prevents tasks stuck forever in 'running' (mirrors Bott's orphan recovery)."""
    with _lock, _conn(db_file) as c:
        cur = c.execute(
            "UPDATE tasks SET status='failed', error='interrupted by restart' WHERE status='running'"
        )
        return cur.rowcount


@dataclass
class Task:
    id: int
    kind: str
    args: dict[str, Any]
    attempts: int = 0


def enqueue(kind: str, args: dict[str, Any], db_file: Optional[str] = None) -> int:
    with _lock, _conn(db_file) as c:
        cur = c.execute(
            "INSERT INTO tasks(kind, args, status, created) VALUES (?,?,'pending',?)",
            (kind, json.dumps(args), time.time()),
        )
        return int(cur.lastrowid)


def next_pending(db_file: Optional[str] = None) -> Optional[Task]:
    with _lock, _conn(db_file) as c:
        row = c.execute(
            "SELECT id, kind, args, attempts FROM tasks WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        c.execute("UPDATE tasks SET status='running' WHERE id=?", (row["id"],))
        return Task(id=row["id"], kind=row["kind"], args=json.loads(row["args"]),
                    attempts=row["attempts"])


def requeue(task_id: int, db_file: Optional[str] = None) -> None:
    """Return a task to the queue and bump its attempt count (for transient retries)."""
    with _lock, _conn(db_file) as c:
        c.execute(
            "UPDATE tasks SET status='pending', attempts=attempts+1 WHERE id=?", (task_id,)
        )


def mark_done(task_id: int, error: Optional[str] = None, db_file: Optional[str] = None) -> None:
    with _lock, _conn(db_file) as c:
        c.execute(
            "UPDATE tasks SET status=?, error=? WHERE id=?",
            ("failed" if error else "done", error, task_id),
        )


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
    db_file: Optional[str] = None,
) -> int:
    with _lock, _conn(db_file) as c:
        cur = c.execute(
            """INSERT INTO traces(channel, thread_ts, owner, name, pr_number,
                 original_verdict, final_verdict, output_json, gate_json, created)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                channel, thread_ts, owner, name, pr_number,
                original_verdict, final_verdict, output_json, gate_json, time.time(),
            ),
        )
        return int(cur.lastrowid)


def latest_trace_for_thread(channel: str, thread_ts: str, db_file: Optional[str] = None) -> Optional[dict]:
    with _conn(db_file) as c:
        row = c.execute(
            "SELECT * FROM traces WHERE channel=? AND thread_ts=? ORDER BY id DESC LIMIT 1",
            (channel, thread_ts),
        ).fetchone()
        return dict(row) if row else None


_MAX_ATTEMPTS = 3
_log = logging.getLogger("review.worker")


class Worker(threading.Thread):
    """Single background worker: polls the queue and runs `handler(task)`. Transient
    handler failures are retried up to _MAX_ATTEMPTS, then marked failed."""

    def __init__(self, handler: Callable[[Task], None], db_file: Optional[str] = None, poll: float = 1.0):
        super().__init__(daemon=True)
        self._handler = handler
        self._db_file = db_file
        self._poll = poll
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            task = next_pending(self._db_file)
            if task is None:
                self._stop.wait(self._poll)
                continue
            try:
                self._handler(task)
                mark_done(task.id, db_file=self._db_file)
            except Exception as e:  # noqa: BLE001
                import traceback

                if task.attempts + 1 < _MAX_ATTEMPTS:
                    _log.warning("task %s failed (attempt %s/%s), retrying: %s",
                                 task.id, task.attempts + 1, _MAX_ATTEMPTS, e)
                    requeue(task.id, db_file=self._db_file)
                    self._stop.wait(min(10, 2 ** task.attempts))  # brief backoff
                else:
                    _log.error("task %s failed permanently after %s attempts: %s",
                               task.id, _MAX_ATTEMPTS, e)
                    mark_done(task.id, error=f"{e}\n{traceback.format_exc()}", db_file=self._db_file)

    def stop(self) -> None:
        self._stop.set()
