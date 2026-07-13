"""Persistance du kiosque d'applications global (table kiosk_applications)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import kiosk_applications

_COLS = (
    kiosk_applications.c.id,
    kiosk_applications.c.name,
    kiosk_applications.c.url,
    kiosk_applications.c.icon,
    kiosk_applications.c.position,
)


async def list_applications(conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            select(*_COLS).order_by(kiosk_applications.c.position, kiosk_applications.c.id)
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def add_application(
    name: str, url: str, icon: str, conn: AsyncConnection
) -> dict[str, Any]:
    """Ajoute un lien en fin de kiosque (position = max + 1). Lève IntegrityError
    si le nom existe déjà — traduit en 409 par la route."""
    next_pos = (
        await conn.execute(
            select(func.coalesce(func.max(kiosk_applications.c.position), 0) + 1)
        )
    ).scalar_one()
    row = (
        await conn.execute(
            kiosk_applications.insert()
            .values(name=name, url=url, icon=icon, position=next_pos)
            .returning(*_COLS)
        )
    ).mappings().one()
    return dict(row)


async def update_application(
    app_id: int, name: str, url: str, icon: str, conn: AsyncConnection
) -> dict[str, Any] | None:
    """Met à jour un lien (position inchangée). None si l'id n'existe pas ;
    IntegrityError si le nouveau nom entre en collision — 409 côté route."""
    row = (
        await conn.execute(
            update(kiosk_applications)
            .where(kiosk_applications.c.id == app_id)
            .values(name=name, url=url, icon=icon, updated_at=func.now())
            .returning(*_COLS)
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def delete_application(app_id: int, conn: AsyncConnection) -> bool:
    result = await conn.execute(
        delete(kiosk_applications).where(kiosk_applications.c.id == app_id)
    )
    return (result.rowcount or 0) > 0
