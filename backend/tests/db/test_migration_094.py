"""Migration 094 — `automation.tree` JSONB, colonnes plates supprimées, `run.trace`."""

from __future__ import annotations

import asyncio
import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from portal.db.migration import _ALEMBIC_INI


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


def _upgrade_sync(database_url: str, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, revision)


async def test_migration_094_tree_and_trace(fresh_postgres_url: str) -> None:
    await asyncio.to_thread(_upgrade_sync, fresh_postgres_url, "093")

    engine = create_async_engine(fresh_postgres_url)
    try:
        async with engine.begin() as conn:
            # Contrat + automate « ancien format » posés AVANT la 094.
            await conn.execute(
                text(
                    "INSERT INTO openapi_contract (id, label, raw_spec) "
                    "VALUES ('c1', 'termix', '{}')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO automation (id, label, event_types, contract_ref, "
                    "operation_id, url, http_method) VALUES ('a1', 'vieille règle', "
                    "'{workspace.created}', 'c1', 'op', 'https://x', 'POST')"
                )
            )

        await asyncio.to_thread(_upgrade_sync, fresh_postgres_url, "094")

        async with engine.connect() as conn:
            row = (
                (await conn.execute(text("SELECT label, tree FROM automation WHERE id = 'a1'")))
                .mappings()
                .one()
            )
            cols = {
                r[0]
                for r in await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'automation'"
                    )
                )
            }
            run_cols = {
                r[0]
                for r in await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'automation_run'"
                    )
                )
            }
    finally:
        await engine.dispose()

    assert row["label"] == "vieille règle"
    assert row["tree"] == {"version": 1, "blocks": []}
    assert "tree" in cols
    for gone in ("url", "http_method", "body_template", "contract_ref", "filter_url"):
        assert gone not in cols
    assert "trace" in run_cols
