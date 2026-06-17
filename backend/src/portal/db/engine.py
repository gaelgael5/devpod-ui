from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from .tables import metadata

_log = structlog.get_logger(__name__)

_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        from portal.settings import get_settings

        url = get_settings().database_url
        if not url:
            raise RuntimeError(
                "DATABASE_URL n'est pas configuré. "
                "Définir la variable d'environnement DATABASE_URL "
                "au format postgresql+asyncpg://user:pass@host/db"
            )
        _engine = create_async_engine(url, pool_size=5, max_overflow=10)
    return _engine


def configure_engine(url: str) -> None:
    """Initialise le moteur avec une URL explicite. Réservé aux tests."""
    global _engine
    _engine = create_async_engine(url, pool_size=1, max_overflow=0)


async def create_all_tables() -> None:
    """Crée toutes les tables déclarées dans metadata (idempotent). Réservé aux tests."""
    async with _get_engine().begin() as conn:
        await conn.run_sync(metadata.create_all)


async def drop_all_tables() -> None:
    """Supprime toutes les tables. Réservé aux tests."""
    async with _get_engine().begin() as conn:
        await conn.run_sync(metadata.drop_all)


async def dispose_engine() -> None:
    """Ferme le pool de connexions proprement."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_conn() -> AsyncGenerator[AsyncConnection, None]:
    """Dependency FastAPI : fournit une connexion dans une transaction."""
    async with _get_engine().begin() as conn:
        yield conn
