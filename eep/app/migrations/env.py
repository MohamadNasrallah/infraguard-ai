"""Alembic environment — DATABASE_URL is sourced from the environment variable."""

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

# Override sqlalchemy.url from environment variable at runtime.
# This keeps credentials out of alembic.ini and out of source control.
database_url = os.getenv(
    "DATABASE_URL",
    "postgresql://infraguard:infraguard@localhost:5432/infraguard",
)
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection required)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
