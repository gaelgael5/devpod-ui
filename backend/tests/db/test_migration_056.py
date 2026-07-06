"""Spec 35 §8.1 — la migration 056 passe par le chemin de production (run_migrations).

Container Postgres dédié (pas la fixture de session) : run_migrations pose
alembic_version et tout le schéma 001→head, on ne veut pas interférer avec le
create_all/drop_all de la fixture db_engine.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from portal.db.migration import run_migrations


@pytest.fixture
def fresh_postgres_url() -> str:
    try:
        import docker

        docker.from_env()
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        pytest.skip(f"Docker non disponible (tests DB skippés) : {exc}")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        yield re.sub(
            r"^postgresql(\+[a-z0-9]+)?://",
            "postgresql+asyncpg://",
            pg.get_connection_url(),
            count=1,
        )


async def test_migration_056_full_chain(fresh_postgres_url: str) -> None:
    await run_migrations(fresh_postgres_url)

    engine = create_async_engine(fresh_postgres_url)
    try:
        async with engine.connect() as conn:
            head = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert head == "056"

            cols = {
                r[0]
                for r in await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_name = 'mcp_profile'"
                    )
                )
            }
            assert "exposed_in_workspaces" in cols

            cols = {
                r[0]
                for r in await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_name = 'mcp_apikey'"
                    )
                )
            }
            assert "workspace_ref" in cols

            cols = {
                r[0]
                for r in await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_name = 'workspaces'"
                    )
                )
            }
            assert "agents" in cols

            idx = (
                await conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes"
                        " WHERE tablename = 'mcp_apikey'"
                        " AND indexname = 'idx_mcp_apikey_workspace_ref'"
                    )
                )
            ).first()
            assert idx is not None

            seed = (
                (
                    await conn.execute(
                        text("SELECT id, label, filename, target_path, enabled FROM agent_type")
                    )
                )
                .mappings()
                .all()
            )
            assert len(seed) == 1
            claude = seed[0]
            assert claude["id"] == "claude"
            assert claude["filename"] == ".mcp.json"
            assert claude["target_path"] == "{{ project_root }}/.mcp.json"
            assert claude["enabled"] is True
    finally:
        await engine.dispose()
