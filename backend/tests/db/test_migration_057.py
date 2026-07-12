"""Migration 057 — types d'agents supplémentaires (Codex, Gemini, Cursor,
Cline, Devin Desktop) : seed correct et templates rendus valides."""

from __future__ import annotations

import asyncio
import json
import re
import tomllib

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from portal.agents.keys import WorkspaceKey
from portal.agents.renderer import build_render_context, render_agent_file
from portal.db.migration import _ALEMBIC_INI

_EXPECTED = {
    "codex": ("config.toml", "{{ home }}/.codex/config.toml"),
    "gemini": ("settings.json", "{{ home }}/.gemini/settings.json"),
    "cursor": ("mcp.json", "{{ project_root }}/.cursor/mcp.json"),
    "cline": ("cline_mcp_settings.json", "{{ home }}/.cline/data/settings/cline_mcp_settings.json"),
    "devin-desktop": ("mcp_config.json", "{{ home }}/.codeium/windsurf/mcp_config.json"),
}


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


def _upgrade_to_057_sync(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    # Révision épinglée (pas `head`) : ce test décrit l'état APRÈS 057 — une
    # migration ultérieure (058 : disable codex/gemini) ne doit pas le casser.
    command.upgrade(cfg, "057")


async def test_migration_057_full_chain(fresh_postgres_url: str) -> None:
    await asyncio.to_thread(_upgrade_to_057_sync, fresh_postgres_url)

    engine = create_async_engine(fresh_postgres_url)
    try:
        async with engine.connect() as conn:
            head = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert head == "057"

            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, label, filename, template, target_path, enabled"
                            " FROM agent_type WHERE id != 'claude'"
                        )
                    )
                )
                .mappings()
                .all()
            )
            by_id = {r["id"]: r for r in rows}
            assert set(by_id) == set(_EXPECTED)

            for agent_id, (filename, target_path) in _EXPECTED.items():
                row = by_id[agent_id]
                assert row["filename"] == filename
                assert row["target_path"] == target_path
                assert row["enabled"] is True
    finally:
        await engine.dispose()


def _render_context_with_servers() -> dict:
    return build_render_context(
        keys=[
            WorkspaceKey("k1", "p1", "défaut", "mcpk_EXEMPLE_xxxxxxxxxxxxxxxx"),
        ],
        mcp_url="https://portal.example.org/mcp/",
        ws_id="alice-mon-ws",
        workspace_name="mon-ws",
        owner_login="alice",
        home="$HOME",
        project_root="/workspaces/alice-mon-ws",
    )


@pytest.mark.parametrize(
    ("agent_id", "kind"),
    [
        ("codex", "toml"),
        ("gemini", "json"),
        ("cursor", "json"),
        ("cline", "json"),
        ("devin-desktop", "json"),
    ],
)
async def test_new_agent_template_renders_to_valid_syntax(
    fresh_postgres_url: str, agent_id: str, kind: str
) -> None:
    """Chaque template doit produire un JSON/TOML syntaxiquement valide — le
    render passe par le sandbox Jinja réel, pas une reconstruction manuelle."""
    await asyncio.to_thread(_upgrade_to_057_sync, fresh_postgres_url)

    engine = create_async_engine(fresh_postgres_url)
    try:
        async with engine.connect() as conn:
            template = (
                await conn.execute(
                    text("SELECT template FROM agent_type WHERE id = :id"), {"id": agent_id}
                )
            ).scalar_one()
    finally:
        await engine.dispose()

    rendered = render_agent_file(template, _render_context_with_servers())
    if kind == "json":
        json.loads(rendered)
    else:
        tomllib.loads(rendered)
