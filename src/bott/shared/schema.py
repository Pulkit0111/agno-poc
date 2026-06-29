"""Single source of truth for Bott's foundation tables (job queue, approvals, per-user
connector tokens). Defined as SQLAlchemy Core so both the runtime init helpers and Alembic
share ONE schema definition — no drift. Runtime DML still lives in the owning modules; this
module owns only the table shapes."""

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


def init_schema(engine=None) -> None:
    """Create all foundation tables if absent (idempotent). The dev/test fast path;
    production schema EVOLUTION goes through Alembic, which targets this same METADATA."""
    from bott.shared.db import get_engine

    METADATA.create_all(engine or get_engine())
