"""Database selector. Postgres when configured (required for the isolation gate and
production); SQLite fallback for quick local construction/dev."""

from __future__ import annotations

import os

from bott.shared.config import agentos_db_path


def build_db():
    """Return an Agno Db: PostgresDb if DATABASE_URL is set, else SqliteDb."""
    url = os.getenv("DATABASE_URL")
    if url:
        from agno.db.postgres import PostgresDb

        return PostgresDb(db_url=url)
    from agno.db.sqlite import SqliteDb

    return SqliteDb(db_file=agentos_db_path())
