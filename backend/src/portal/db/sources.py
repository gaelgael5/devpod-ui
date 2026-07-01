from __future__ import annotations

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import compose_catalog_sources, profile_sources, recipe_sources

_DEFAULT_RECIPE_SOURCE = (
    "https://raw.githubusercontent.com/ag-flow/ressources/refs/heads/main/recipes/toc.txt"
)
_DEFAULT_PROFILE_SOURCE = (
    "https://raw.githubusercontent.com/ag-flow/ressources/refs/heads/main/profiles/toc.txt"
)
_DEFAULT_COMPOSE_SOURCE = (
    "https://raw.githubusercontent.com/ag-flow/ressources/refs/heads/main/composes/toc.txt"
)


async def load_recipe_sources(conn: AsyncConnection) -> list[str]:
    rows = (
        await conn.execute(
            select(recipe_sources.c.url)
            .where(recipe_sources.c.enabled.is_(True))
            .order_by(recipe_sources.c.position)
        )
    ).scalars().all()
    return list(rows) if rows else [_DEFAULT_RECIPE_SOURCE]


async def save_recipe_sources(sources: list[str], conn: AsyncConnection) -> None:
    await conn.execute(delete(recipe_sources))
    if sources:
        await conn.execute(
            insert(recipe_sources),
            [{"url": url, "position": i} for i, url in enumerate(sources)],
        )


async def load_profile_sources(conn: AsyncConnection) -> list[str]:
    rows = (
        await conn.execute(
            select(profile_sources.c.url)
            .where(profile_sources.c.enabled.is_(True))
            .order_by(profile_sources.c.position)
        )
    ).scalars().all()
    return list(rows) if rows else [_DEFAULT_PROFILE_SOURCE]


async def save_profile_sources(sources: list[str], conn: AsyncConnection) -> None:
    await conn.execute(delete(profile_sources))
    if sources:
        await conn.execute(
            insert(profile_sources),
            [{"url": url, "position": i} for i, url in enumerate(sources)],
        )


async def load_compose_sources(conn: AsyncConnection) -> list[str]:
    rows = (
        await conn.execute(
            select(compose_catalog_sources.c.url)
            .where(compose_catalog_sources.c.enabled.is_(True))
            .order_by(compose_catalog_sources.c.position)
        )
    ).scalars().all()
    return list(rows) if rows else [_DEFAULT_COMPOSE_SOURCE]


async def save_compose_sources(sources: list[str], conn: AsyncConnection) -> None:
    await conn.execute(delete(compose_catalog_sources))
    if sources:
        await conn.execute(
            insert(compose_catalog_sources),
            [{"url": url, "position": i} for i, url in enumerate(sources)],
        )
