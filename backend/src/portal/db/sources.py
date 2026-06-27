from __future__ import annotations

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import profile_sources, recipe_sources

_DEFAULT_RECIPE_SOURCE = (
    "https://raw.githubusercontent.com/gaelgael5/devpod-ui/dev/recipes/toc.txt"
)
_DEFAULT_PROFILE_SOURCE = (
    "https://raw.githubusercontent.com/gaelgael5/devpod-ui/dev/profiles/"
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
