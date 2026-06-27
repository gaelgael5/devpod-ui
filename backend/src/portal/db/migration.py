from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

_log = structlog.get_logger(__name__)

# Remonte de src/portal/db/ → backend/ où alembic.ini est copié dans l'image (/app/).
_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"


def _upgrade_sync(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


async def run_migrations(database_url: str) -> None:
    _log.info("db_migrations_start", ini=str(_ALEMBIC_INI))
    await asyncio.to_thread(_upgrade_sync, database_url)
    _log.info("db_migrations_done")
