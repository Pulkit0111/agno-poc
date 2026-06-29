"""Database selection. Postgres in production (DATABASE_URL); SQLite only under pytest.

`build_db()` returns the Agno Db for sessions/memory/traces. `get_engine()` returns a
SQLAlchemy engine for our own foundation tables (job queue, secrets, approvals)."""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from bott.shared.config import agentos_db_path, database_url

_engine: Engine | None = None


def under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def build_db():
    """Agno Db: PostgresDb when DATABASE_URL is set, else SqliteDb (tests/local only)."""
    url = database_url()
    if url:
        from agno.db.postgres import PostgresDb

        return PostgresDb(db_url=url)
    from agno.db.sqlite import SqliteDb

    return SqliteDb(db_file=agentos_db_path())


def get_engine(fresh: bool = False) -> Engine:
    """SQLAlchemy engine for our foundation tables. DATABASE_URL in prod; a local SQLite
    file otherwise (tests). `fresh=True` rebuilds (used by tests that flip env)."""
    global _engine
    if _engine is not None and not fresh:
        return _engine
    url = database_url()
    if url:
        # Normalize to the psycopg driver SQLAlchemy expects.
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        _engine = create_engine(url, pool_pre_ping=True)
    else:
        _engine = create_engine(f"sqlite:///{agentos_db_path()}")
    return _engine
