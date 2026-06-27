from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Importer la MetaData afin qu'Alembic détecte les tables déclarées.
from portal.db.tables import metadata

alembic_cfg = context.config

if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)

target_metadata = metadata


def _get_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        url = alembic_cfg.get_main_option("sqlalchemy.url") or ""
    if not url:
        raise RuntimeError(
            "DATABASE_URL introuvable. "
            "Définir la variable d'environnement DATABASE_URL "
            "au format postgresql+asyncpg://user:pass@host/db"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)  # type: ignore[arg-type]
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(_get_url(), poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
