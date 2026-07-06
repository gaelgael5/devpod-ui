"""Migration 058 — colonne `mode` sur agent_type (spec 35, addendum merge).

`mode ∈ {replace, merge}` distingue les clients à fichier dédié MCP (symlink
vers un mount ro, comportement historique = `replace`) des clients à fichier de
config partagé (Codex, Gemini) qui exigent un merge du connecteur dans le
fichier existant (`merge`). Codex/Gemini sont désactivés par cette migration
jusqu'à ce que le mécanisme de merge soit livré (réactivés en fin de chantier).
"""

from __future__ import annotations

import asyncio
import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from portal.db.migration import _ALEMBIC_INI

# mode attendu par agent après upgrade 058.
_REPLACE = {"claude", "cursor", "cline", "devin-desktop"}
_MERGE = {"codex", "gemini"}


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


def _run_migrations_sync(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def _downgrade_sync(database_url: str, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(cfg, revision)


async def _mode_column_exists(conn) -> bool:
    row = (
        await conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns"
                " WHERE table_name = 'agent_type' AND column_name = 'mode'"
            )
        )
    ).first()
    return row is not None


async def test_migration_058_adds_mode_and_disables_shared_file_clients(
    fresh_postgres_url: str,
) -> None:
    await asyncio.to_thread(_run_migrations_sync, fresh_postgres_url)

    engine = create_async_engine(fresh_postgres_url)
    try:
        async with engine.connect() as conn:
            head = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert head == "058"

            assert await _mode_column_exists(conn)

            rows = (
                (await conn.execute(text("SELECT id, mode, enabled FROM agent_type")))
                .mappings()
                .all()
            )
            by_id = {r["id"]: r for r in rows}

            for agent_id in _REPLACE:
                assert by_id[agent_id]["mode"] == "replace", agent_id
                assert by_id[agent_id]["enabled"] is True, agent_id

            for agent_id in _MERGE:
                assert by_id[agent_id]["mode"] == "merge", agent_id
                # Désactivés tant que le merge n'est pas livré.
                assert by_id[agent_id]["enabled"] is False, agent_id
    finally:
        await engine.dispose()


async def test_migration_058_default_is_replace(fresh_postgres_url: str) -> None:
    """Une ligne insérée sans `mode` explicite retombe sur 'replace'."""
    await asyncio.to_thread(_run_migrations_sync, fresh_postgres_url)

    engine = create_async_engine(fresh_postgres_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO agent_type (id, label, filename, template, target_path)"
                    " VALUES ('probe', 'Probe', 'x.json', '{}', '{{ home }}/x.json')"
                )
            )
        async with engine.connect() as conn:
            mode = (
                await conn.execute(text("SELECT mode FROM agent_type WHERE id = 'probe'"))
            ).scalar_one()
            assert mode == "replace"
    finally:
        await engine.dispose()


async def test_migration_058_downgrade_restores_057_state(fresh_postgres_url: str) -> None:
    """Downgrade : la colonne `mode` disparaît et codex/gemini sont réactivés."""
    await asyncio.to_thread(_run_migrations_sync, fresh_postgres_url)
    await asyncio.to_thread(_downgrade_sync, fresh_postgres_url, "057")

    engine = create_async_engine(fresh_postgres_url)
    try:
        async with engine.connect() as conn:
            head = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert head == "057"

            assert not await _mode_column_exists(conn)

            rows = (await conn.execute(text("SELECT id, enabled FROM agent_type"))).mappings().all()
            by_id = {r["id"]: r for r in rows}
            for agent_id in _MERGE:
                assert by_id[agent_id]["enabled"] is True, agent_id
    finally:
        await engine.dispose()
