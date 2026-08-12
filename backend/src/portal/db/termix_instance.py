"""Couche DB du registre d'instances Termix (`termix_instance`, spec 18 T2).

Invariant : au plus une instance `is_default=True`. Tenu applicativement — poser
un défaut décoche les autres. La transaction est ouverte par l'appelant.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import termix_instance as _t

_EDITABLE = ("name", "url", "apikey_secret", "oidc_client_id", "is_default")


async def _clear_defaults(conn: AsyncConnection, *, exclude_id: str | None = None) -> None:
    stmt = update(_t).where(_t.c.is_default.is_(True)).values(is_default=False)
    if exclude_id is not None:
        stmt = stmt.where(_t.c.id != exclude_id)
    await conn.execute(stmt)


async def create(
    conn: AsyncConnection,
    *,
    name: str,
    url: str,
    apikey_secret: str,
    oidc_client_id: str = "",
    is_default: bool = False,
) -> dict[str, Any]:
    """Crée une instance. Si `is_default`, décoche les autres (invariant)."""
    instance_id = uuid.uuid4().hex
    if is_default:
        await _clear_defaults(conn)
    stmt = (
        pg_insert(_t)
        .values(
            id=instance_id,
            name=name,
            url=url,
            apikey_secret=apikey_secret,
            oidc_client_id=oidc_client_id,
            is_default=is_default,
        )
        .returning(_t)
    )
    return dict((await conn.execute(stmt)).mappings().one())


async def get(conn: AsyncConnection, instance_id: str) -> dict[str, Any] | None:
    row = (await conn.execute(select(_t).where(_t.c.id == instance_id))).mappings().first()
    return dict(row) if row is not None else None


async def list_all(conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = (await conn.execute(select(_t).order_by(_t.c.name))).mappings().all()
    return [dict(r) for r in rows]


async def get_default(conn: AsyncConnection) -> dict[str, Any] | None:
    row = (await conn.execute(select(_t).where(_t.c.is_default.is_(True)))).mappings().first()
    return dict(row) if row is not None else None


async def name_exists(conn: AsyncConnection, name: str, *, exclude_id: str | None = None) -> bool:
    stmt = select(_t.c.id).where(_t.c.name == name)
    if exclude_id is not None:
        stmt = stmt.where(_t.c.id != exclude_id)
    return (await conn.execute(stmt)).first() is not None


async def update_instance(
    conn: AsyncConnection, instance_id: str, **fields: Any
) -> dict[str, Any] | None:
    """Met à jour les champs fournis (parmi _EDITABLE). None si absent."""
    values = {k: v for k, v in fields.items() if k in _EDITABLE and v is not None}
    if not values:
        return await get(conn, instance_id)
    if values.get("is_default"):
        await _clear_defaults(conn, exclude_id=instance_id)
    values["updated_at"] = func.now()
    stmt = update(_t).where(_t.c.id == instance_id).values(**values).returning(_t)
    row = (await conn.execute(stmt)).mappings().first()
    return dict(row) if row is not None else None


async def delete_instance(conn: AsyncConnection, instance_id: str) -> bool:
    result = await conn.execute(delete(_t).where(_t.c.id == instance_id))
    return bool(result.rowcount)
