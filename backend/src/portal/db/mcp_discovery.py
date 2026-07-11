"""Persistance des sources de découverte MCP (table mcp_discovery_source)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import mcp_discovery_source

_COLS = (
    mcp_discovery_source.c.id,
    mcp_discovery_source.c.label,
    mcp_discovery_source.c.slug,
    mcp_discovery_source.c.url,
    mcp_discovery_source.c.secret_slug,
)


async def list_sources(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    """Sources de l'utilisateur (jamais la valeur du secret, seulement son slug)."""
    rows = (
        (
            await conn.execute(
                select(*_COLS)
                .where(mcp_discovery_source.c.login == login)
                .order_by(mcp_discovery_source.c.label)
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def get_source(login: str, source_id: int, conn: AsyncConnection) -> dict[str, Any] | None:
    row = (
        (
            await conn.execute(
                select(*_COLS).where(
                    mcp_discovery_source.c.login == login,
                    mcp_discovery_source.c.id == source_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


async def create_source(
    login: str, label: str, slug: str, url: str, secret_slug: str, conn: AsyncConnection
) -> dict[str, Any]:
    """Insère une source et renvoie sa représentation (id + champs publics)."""
    row = (
        (
            await conn.execute(
                insert(mcp_discovery_source)
                .values(login=login, label=label, slug=slug, url=url, secret_slug=secret_slug)
                .returning(*_COLS)
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def delete_source(login: str, source_id: int, conn: AsyncConnection) -> bool:
    """Supprime une source de l'utilisateur. True si une ligne a été retirée."""
    result = await conn.execute(
        delete(mcp_discovery_source).where(
            mcp_discovery_source.c.login == login,
            mcp_discovery_source.c.id == source_id,
        )
    )
    return (result.rowcount or 0) > 0
