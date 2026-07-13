"""Persistance du kiosque d'applications (table user_applications)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import user_applications


async def list_applications(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            select(
                user_applications.c.id,
                user_applications.c.name,
                user_applications.c.url,
                user_applications.c.icon,
                user_applications.c.position,
            )
            .where(user_applications.c.login == login)
            .order_by(user_applications.c.position, user_applications.c.id)
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def add_application(
    login: str, name: str, url: str, icon: str, conn: AsyncConnection
) -> dict[str, Any]:
    """Ajoute un lien en fin de kiosque (position = max + 1). Lève IntegrityError
    si (login, name) existe déjà — traduit en 409 par la route."""
    next_pos = (
        await conn.execute(
            select(func.coalesce(func.max(user_applications.c.position), 0) + 1).where(
                user_applications.c.login == login
            )
        )
    ).scalar_one()
    row = (
        await conn.execute(
            user_applications.insert()
            .values(login=login, name=name, url=url, icon=icon, position=next_pos)
            .returning(
                user_applications.c.id,
                user_applications.c.name,
                user_applications.c.url,
                user_applications.c.icon,
                user_applications.c.position,
            )
        )
    ).mappings().one()
    return dict(row)


async def delete_application(login: str, app_id: int, conn: AsyncConnection) -> bool:
    """Supprime un lien du kiosque de `login`. Le WHERE login garantit qu'on ne
    supprime jamais la ligne d'un autre utilisateur. True si une ligne a existé."""
    result = await conn.execute(
        delete(user_applications)
        .where(user_applications.c.id == app_id)
        .where(user_applications.c.login == login)
    )
    return (result.rowcount or 0) > 0
