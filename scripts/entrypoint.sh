#!/bin/sh
# Container entrypoint for the bott image: bring the database under Alembic control,
# then exec the real command (default: bott-app).
#
# Why this exists: the app creates its schema with SQLAlchemy create_all() at import
# (src/bott/shared/schema.py init_schema), so on a fresh database `alembic_version` is
# never written. If a later deploy just ran `alembic upgrade head`, Alembic would try to
# replay the baseline migration against tables that already exist and fail. So:
#
#   - no alembic_version table  -> fresh (or pre-Alembic) DB: `alembic stamp head`.
#     The tables themselves come from the app's create_all() moments later; stamping
#     records "you are already at head" so future upgrades apply cleanly.
#   - alembic_version exists    -> normally managed DB: `alembic upgrade head`.
#
# Waiting for Postgres is compose's job (depends_on: condition: service_healthy); under
# plain `docker run` against SQLite there is nothing to wait for. PATH already contains
# /app/.venv/bin (set in the Dockerfile), so `python` and `alembic` are the venv's.

set -eu

# Uses the app's own engine resolution (bott.shared.db.get_engine) so DATABASE_URL —
# or the SQLite fallback — is interpreted exactly as the app and migrations/env.py do.
if python -c "
import sys
from sqlalchemy import inspect
from bott.shared.db import get_engine
sys.exit(0 if inspect(get_engine()).has_table('alembic_version') else 1)
"; then
    echo "entrypoint: alembic_version found — applying pending migrations (alembic upgrade head)"
    alembic upgrade head
else
    echo "entrypoint: no alembic_version table — stamping head (schema comes from the app's create_all)"
    alembic stamp head
fi

exec "$@"
