# Alembic Migrations

## Single source of truth

`src/bott/shared/schema.py` owns all table shapes (SQLAlchemy Core `Table`
definitions collected under `METADATA`).  Both the runtime helper and Alembic
import that same `METADATA` — there is no duplication or drift risk.

## Two paths for schema creation

| Path | When to use |
|---|---|
| `init_schema()` (`CREATE TABLE IF NOT EXISTS`) | Fresh dev/test DB, or first deploy to a brand-new Postgres instance with no existing tables. |
| `alembic upgrade head` | Evolving a Postgres database that already has data. |

## Onboarding an existing database (created via `init_schema`)

If your database was created by `init_schema` (not by Alembic), mark the
baseline as already applied before using Alembic for future changes:

```bash
alembic stamp head
```

From that point on, use the normal workflow for any schema changes:

```bash
# 1. Edit schema.py to reflect the desired state.
# 2. Generate a migration.
alembic revision --autogenerate -m "describe the change"
# 3. Review the generated file in migrations/versions/.
# 4. Apply it.
alembic upgrade head
```

## Configuration

`env.py` derives the database URL from `bott.shared.db.get_engine()`, which
reads `DATABASE_URL` from the environment — identical to the application.
The `sqlalchemy.url` key in `alembic.ini` is intentionally left blank.
