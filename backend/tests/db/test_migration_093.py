"""Migration 093 — colonnes `bastion_*` / `events_*` sur `global_config`.

Vérifie que l'upgrade ajoute les colonnes avec les défauts alignés sur les
modèles pydantic : une ligne existante (config posée avant la migration)
récupère `bastion_port=2222`, `bastion_apikey_secret='termix-apikey'`, etc.
"""

from __future__ import annotations

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


async def test_migration_093_adds_bastion_and_events_columns(fresh_postgres_url: str) -> None:
    import asyncio

    await asyncio.to_thread(_upgrade_sync, fresh_postgres_url, "092")

    engine = create_async_engine(fresh_postgres_url)
    try:
        async with engine.begin() as conn:
            # Ligne posée AVANT la 093 : simule une instance déjà configurée.
            await conn.execute(
                text(
                    "INSERT INTO global_config (id, version, base_domain, external_url, "
                    "oidc_issuer, oidc_client_id, oidc_scopes) "
                    "VALUES (1, '1', 'dev.example.com', 'https://dev.example.com', "
                    "'https://auth.example.com', 'portal', '{openid}')"
                )
            )

        await asyncio.to_thread(_upgrade_sync, fresh_postgres_url, "093")

        async with engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT bastion_enabled, bastion_api_url, bastion_host, "
                            "bastion_port, bastion_role, bastion_apikey_secret, "
                            "events_enabled, events_workflow_base_url, events_source_id, "
                            "events_secret_slug, events_source_uri, events_types "
                            "FROM global_config WHERE id = 1"
                        )
                    )
                )
                .mappings()
                .one()
            )
    finally:
        await engine.dispose()

    assert row["bastion_enabled"] is False
    assert row["bastion_api_url"] == ""
    assert row["bastion_host"] == ""
    assert row["bastion_port"] == 2222
    assert row["bastion_role"] == ""
    assert row["bastion_apikey_secret"] == "termix-apikey"
    assert row["events_enabled"] is False
    assert row["events_workflow_base_url"] == ""
    assert row["events_source_id"] == ""
    assert row["events_secret_slug"] == "workflow_events_hmac"
    assert row["events_source_uri"] == "urn:yoops:devpod"
    assert list(row["events_types"]) == []
