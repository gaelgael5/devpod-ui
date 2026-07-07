"""Migration 059 — templates Codex/Gemini en fragment possédé (spec 35b T8).

Le contrat du fragment est celui du cœur de merge : clé de tête conventionnelle
(`mcp_servers` TOML / `mcpServers` JSON), toutes les entrées préfixées `portal-`.
On vérifie ici que les templates seedés rendent un fragment que `merge_config`
accepte ET qui préserve un réglage utilisateur existant.
"""

from __future__ import annotations

import asyncio
import json
import re
import tomllib

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from portal.agents.keys import WorkspaceKey
from portal.agents.merge import merge_config
from portal.agents.renderer import build_render_context, render_agent_file
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


def _downgrade_sync(database_url: str, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(cfg, revision)


async def _fetch_template(database_url: str, agent_id: str) -> str:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT template FROM agent_type WHERE id = :id"), {"id": agent_id}
                )
            ).scalar_one()
    finally:
        await engine.dispose()


def _context() -> dict:
    return build_render_context(
        keys=[WorkspaceKey("k1", "p1", "défaut", "mcpk_EXEMPLE_xxxxxxxxxxxxxxxx")],
        mcp_url="https://portal.example.org/mcp/",
        ws_id="alice-mon-ws",
        workspace_name="mon-ws",
        owner_login="alice",
        home="/home/vscode",
        project_root="/workspaces/alice-mon-ws",
    )


async def test_codex_fragment_merges_and_preserves_user_settings(
    fresh_postgres_url: str,
) -> None:
    await asyncio.to_thread(_upgrade_sync, fresh_postgres_url, "059")
    template = await _fetch_template(fresh_postgres_url, "codex")

    fragment = render_agent_file(template, _context())
    servers = tomllib.loads(fragment)["mcp_servers"]
    assert servers and all(name.startswith("portal-") for name in servers)

    existing = '# réglage\nmodel = "o4"\n[mcp_servers.perso]\nurl = "https://x/"\n'
    merged = merge_config(existing, fragment, fmt="toml", servers_key="mcp_servers")
    doc = tomllib.loads(merged)
    assert doc["model"] == "o4"  # réglage utilisateur préservé
    assert "perso" in doc["mcp_servers"]  # serveur utilisateur préservé
    assert "portal-defaut" in doc["mcp_servers"]  # serveur du portail injecté


async def test_gemini_fragment_merges_and_preserves_user_settings(
    fresh_postgres_url: str,
) -> None:
    await asyncio.to_thread(_upgrade_sync, fresh_postgres_url, "059")
    template = await _fetch_template(fresh_postgres_url, "gemini")

    fragment = render_agent_file(template, _context())
    servers = json.loads(fragment)["mcpServers"]
    assert servers and all(name.startswith("portal-") for name in servers)

    existing = json.dumps({"theme": "dark", "mcpServers": {"perso": {"httpUrl": "https://x/"}}})
    merged = merge_config(existing, fragment, fmt="json", servers_key="mcpServers")
    doc = json.loads(merged)
    assert doc["theme"] == "dark"
    assert "perso" in doc["mcpServers"]
    assert "portal-defaut" in doc["mcpServers"]


async def test_merge_clients_stay_disabled_until_t9(fresh_postgres_url: str) -> None:
    await asyncio.to_thread(_upgrade_sync, fresh_postgres_url, "059")
    engine = create_async_engine(fresh_postgres_url)
    try:
        async with engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, enabled, mode FROM agent_type"
                            " WHERE id IN ('codex', 'gemini')"
                        )
                    )
                )
                .mappings()
                .all()
            )
    finally:
        await engine.dispose()
    assert {r["id"]: (r["enabled"], r["mode"]) for r in rows} == {
        "codex": (False, "merge"),
        "gemini": (False, "merge"),
    }


async def test_downgrade_restores_057_templates(fresh_postgres_url: str) -> None:
    await asyncio.to_thread(_upgrade_sync, fresh_postgres_url, "059")
    await asyncio.to_thread(_downgrade_sync, fresh_postgres_url, "058")
    template = await _fetch_template(fresh_postgres_url, "codex")
    assert "portal-" not in template
    assert "[mcp_servers.{{ s.name }}]" in template
