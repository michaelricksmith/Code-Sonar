from __future__ import annotations

import os

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.persistence.schema import metadata

config = context.config
database_url = os.environ.get("CODESONAR_DATABASE_URL", "").strip()
if not database_url:
    raise RuntimeError("CODESONAR_DATABASE_URL is required for migrations")
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(url=database_url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
