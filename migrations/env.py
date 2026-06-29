from logging.config import fileConfig

from alembic import context

# Alembic Config object — provides access to the values within the .ini file.
config = context.config

# Set up Python logging from the ini file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Single source of truth: the shared SQLAlchemy MetaData from the app.
from bott.shared.schema import METADATA  # noqa: E402

target_metadata = METADATA


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout, no live connection).

    Uses the app engine's URL so DATABASE_URL is honoured identically to the app.
    """
    from bott.shared.db import get_engine

    url = get_engine().url.render_as_string(hide_password=False)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (live connection).

    Reuses the app's engine so DATABASE_URL is the single configuration point.
    """
    from bott.shared.db import get_engine

    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
