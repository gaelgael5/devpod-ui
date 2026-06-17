"""Fixtures partagées pour les tests de la couche base de données.

Architecture des fixtures :
  postgres_container (session) — démarre un container PostgreSQL une fois pour toute la session
  db_engine         (function) — crée toutes les tables, les détruit après chaque test
  db_conn           (function) — connexion dans une transaction rollbackée automatiquement

Usage dans un test :

    async def test_something(db_conn):
        await db_conn.execute(insert(my_table).values(...))
        result = await db_conn.execute(select(my_table))
        ...
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

import portal.db.engine as _engine_module
from portal.db.tables import metadata


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """Démarre un container PostgreSQL et retourne son URL asyncpg.

    Le container vit toute la session pytest et est détruit à la fin.
    Nécessite Docker disponible sur la machine — skippe si absent.
    """
    try:
        import docker

        docker.from_env()
    except Exception as exc:
        pytest.skip(f"Docker non disponible (tests DB skippés) : {exc}")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        # testcontainers retourne une URL psycopg2 — on adapte pour asyncpg
        url = pg.get_connection_url().replace("postgresql://", "postgresql+asyncpg://", 1)
        yield url


@pytest.fixture
async def db_engine(postgres_url: str) -> AsyncEngine:
    """Crée un moteur isolé, applique le schéma, détruit les tables après le test."""
    engine = create_async_engine(postgres_url, pool_size=1, max_overflow=0)
    # Patch le moteur global pour que les fonctions du store l'utilisent
    _engine_module._engine = engine

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)

    await engine.dispose()
    _engine_module._engine = None


@pytest.fixture
async def db_conn(db_engine: AsyncEngine) -> AsyncConnection:
    """Connexion dans une transaction imbriquée (SAVEPOINT).

    La transaction est rollbackée après chaque test : isolation parfaite
    sans avoir à recréer les tables.
    """
    async with db_engine.connect() as conn:
        await conn.begin_nested()
        yield conn
        await conn.rollback()
