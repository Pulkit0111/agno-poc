"""Single source of truth for Bott's foundation tables (job queue, approvals, per-user
connector tokens, settings, dedup tables, review traces). Defined as SQLAlchemy Core so
both the runtime init helpers and Alembic share ONE schema definition — no drift. Runtime
DML still lives in the owning modules; this module owns only the table shapes."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
)
from sqlalchemy import text as _sql_text

METADATA = MetaData()

# Job queue (shared/persistence/queue.py owns the DML).
JOBS = Table(
    "jobs",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", Text, nullable=False),
    Column("args", Text, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=_sql_text("'pending'")),
    Column("attempts", Integer, nullable=False, server_default=_sql_text("0")),
    Column("dedup_key", Text),
    Column("error", Text),
    Column("created", Float, nullable=False),
)
Index("idx_jobs_pending", JOBS.c.status, JOBS.c.id)

# Human approval gate (shared/approvals.py owns the DML).
APPROVALS = Table(
    "approvals",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=_sql_text("'pending'")),
    Column("decided_by", Text),
    Column("payload", Text),  # JSON: parameters for the approved action (e.g. implement-job args)
    Column("created", Float, nullable=False),
)

# Per-user connector tokens (ciphertext at rest; one row per (user_id, provider)).
CONNECTOR_TOKENS = Table(
    "connector_tokens",
    METADATA,
    Column("user_id", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("token", Text, nullable=False),
    Column("created", Float),
    PrimaryKeyConstraint("user_id", "provider"),
)


# Key-value settings store (shared/persistence/records.py owns the DML).
SETTINGS = Table(
    "settings",
    METADATA,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
)

# GitHub webhook delivery dedup (shared/persistence/records.py owns the DML).
GITHUB_DELIVERIES = Table(
    "github_deliveries",
    METADATA,
    Column("delivery_id", Text, primary_key=True),
    Column("created", Float, nullable=False),
)

# Commit-level review dedup (shared/persistence/records.py owns the DML).
REVIEWED_COMMITS = Table(
    "reviewed_commits",
    METADATA,
    Column("repo_sha", Text, primary_key=True),
    Column("created", Float, nullable=False),
)

# Review traces for re-review continuity (shared/persistence/records.py owns the DML).
REVIEW_TRACES = Table(
    "review_traces",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", Text),
    Column("thread_ts", Text),
    Column("owner", Text),
    Column("name", Text),
    Column("pr_number", Integer),
    Column("original_verdict", Text),
    Column("final_verdict", Text),
    Column("output_json", Text),
    Column("gate_json", Text),
    Column("created", Float, nullable=False),
)
Index("idx_traces_thread", REVIEW_TRACES.c.channel, REVIEW_TRACES.c.thread_ts, REVIEW_TRACES.c.id)


def init_schema(engine=None) -> None:
    """Create all foundation tables if absent (idempotent). The dev/test fast path;
    production schema EVOLUTION goes through Alembic, which targets this same METADATA."""
    from bott.shared.db import get_engine

    METADATA.create_all(engine or get_engine())
