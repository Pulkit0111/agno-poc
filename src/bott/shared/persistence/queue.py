"""Postgres-backed job queue (split-ready). Workers claim rows with FOR UPDATE SKIP
LOCKED so any number of worker processes claim safely. Runs in-process today; the same
worker_main runs as a standalone process/container later with no change.

Under SQLite (tests only) the SKIP LOCKED clause is omitted — multi-worker safety is a
Postgres guarantee and is exercised by the Postgres-gated test."""

from __future__ import annotations

import json
import threading
import time
import traceback
from typing import Any, Callable, Optional

from sqlalchemy import text

from bott.shared.db import get_engine
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.queue")
_MAX_ATTEMPTS = 3


def _is_postgres() -> bool:
    return get_engine().url.get_backend_name().startswith("postgre")


def init_queue() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY {autoinc},
        kind TEXT NOT NULL,
        args TEXT NOT NULL,
        user_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        dedup_key TEXT,
        error TEXT,
        created DOUBLE PRECISION NOT NULL
    )
    """
    autoinc = "" if _is_postgres() else "AUTOINCREMENT"
    # Postgres needs SERIAL/identity; use a portable form per backend.
    if _is_postgres():
        ddl = ddl.replace("INTEGER PRIMARY KEY ", "SERIAL PRIMARY KEY ")
    with get_engine().begin() as c:
        c.execute(text(ddl.format(autoinc=autoinc)))
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_jobs_pending ON jobs(status, id)"
        ))


def enqueue(kind: str, args: dict[str, Any], user_id: str,
            dedup_key: Optional[str] = None) -> int:
    with get_engine().begin() as c:
        if dedup_key:
            row = c.execute(text(
                "SELECT id FROM jobs WHERE dedup_key=:k AND status='pending'"
            ), {"k": dedup_key}).fetchone()
            if row:
                return int(row[0])
        if _is_postgres():
            res = c.execute(text(
                "INSERT INTO jobs(kind,args,user_id,status,dedup_key,created) "
                "VALUES (:kind,:args,:uid,'pending',:dk,:ts) RETURNING id"
            ), {"kind": kind, "args": json.dumps(args), "uid": user_id,
                 "dk": dedup_key, "ts": time.time()})
            return int(res.fetchone()[0])
        else:
            # SQLite: use lastrowid (RETURNING also works on 3.35+, but
            # lastrowid is more portable across driver/version combinations)
            res = c.execute(text(
                "INSERT INTO jobs(kind,args,user_id,status,dedup_key,created) "
                "VALUES (:kind,:args,:uid,'pending',:dk,:ts)"
            ), {"kind": kind, "args": json.dumps(args), "uid": user_id,
                 "dk": dedup_key, "ts": time.time()})
            return int(res.lastrowid)


def claim_one() -> Optional[dict]:
    skip = "FOR UPDATE SKIP LOCKED" if _is_postgres() else ""
    with get_engine().begin() as c:
        row = c.execute(text(
            f"SELECT id,kind,args,user_id,attempts FROM jobs "
            f"WHERE status='pending' ORDER BY id LIMIT 1 {skip}"
        )).fetchone()
        if not row:
            return None
        c.execute(text("UPDATE jobs SET status='running' WHERE id=:id"), {"id": row[0]})
        return {"id": int(row[0]), "kind": row[1], "args": json.loads(row[2]),
                "user_id": row[3], "attempts": int(row[4])}


def complete(job_id: int, error: Optional[str] = None) -> None:
    with get_engine().begin() as c:
        c.execute(text("UPDATE jobs SET status=:s, error=:e WHERE id=:id"),
                  {"s": "failed" if error else "done", "e": error, "id": job_id})


def requeue(job_id: int) -> None:
    with get_engine().begin() as c:
        c.execute(text(
            "UPDATE jobs SET status='pending', attempts=attempts+1 WHERE id=:id"
        ), {"id": job_id})


def recover_orphans() -> int:
    with get_engine().begin() as c:
        res = c.execute(text(
            "UPDATE jobs SET status='failed', error='interrupted by restart' "
            "WHERE status='running'"))
        return res.rowcount or 0


def worker_main(handler: Callable[[dict], None], poll: float = 1.0,
                stop: Optional[threading.Event] = None) -> None:
    """Claim -> handle -> complete loop. Run as a thread today or a process tomorrow."""
    init_queue()
    recover_orphans()
    stop = stop or threading.Event()
    while not stop.is_set():
        job = claim_one()
        if job is None:
            stop.wait(poll)
            continue
        try:
            handler(job)
            complete(job["id"])
        except Exception as e:  # noqa: BLE001
            if job["attempts"] + 1 < _MAX_ATTEMPTS:
                log.warning("job %s failed (attempt %s), retrying: %s",
                            job["id"], job["attempts"] + 1, e)
                requeue(job["id"])
                stop.wait(min(10, 2 ** job["attempts"]))
            else:
                complete(job["id"], error=f"{e}\n{traceback.format_exc()}")
