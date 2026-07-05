"""Persistance du registre de services (hub Services & Security).

Adresses de services externes utiles au travail de l'utilisateur, avec le
profil MCP permettant d'y accéder (name, url, mcp_profile_id). v1 : CRUD simple,
comportements additionnels à venir (cf. spec ultérieure).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import mcp_profile as _profiles
from .tables import user_services as _t


def _row(row: Any) -> dict[str, Any]:
    d = dict(row)
    for k in ("created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


async def list_services(conn: AsyncConnection, owner_login: str) -> list[dict[str, Any]]:
    """Services de l'utilisateur, avec le nom du profil MCP joint (affichage).

    `mcp_profile_name` est None si aucun profil n'est associé, ou si le profil
    associé a été supprimé depuis (mcp_profile_id repasse à NULL via SET NULL).
    """
    stmt = (
        select(_t, _profiles.c.name.label("mcp_profile_name"))
        .select_from(_t.outerjoin(_profiles, _t.c.mcp_profile_id == _profiles.c.id))
        .where(_t.c.owner_login == owner_login)
        .order_by(_t.c.name)
    )
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row(r) for r in rows]


async def get_service(
    conn: AsyncConnection, owner_login: str, service_id: str
) -> dict[str, Any] | None:
    row = (
        await conn.execute(
            select(_t).where(and_(_t.c.id == service_id, _t.c.owner_login == owner_login))
        )
    ).mappings().one_or_none()
    return _row(row) if row is not None else None


async def create_service(
    conn: AsyncConnection,
    *,
    owner_login: str,
    name: str,
    url: str,
    mcp_profile_id: str | None,
) -> str:
    sid = str(uuid.uuid4())
    await conn.execute(
        insert(_t).values(
            id=sid, owner_login=owner_login, name=name, url=url, mcp_profile_id=mcp_profile_id
        )
    )
    return sid


async def update_service(
    conn: AsyncConnection,
    owner_login: str,
    service_id: str,
    *,
    name: str,
    url: str,
    mcp_profile_id: str | None,
) -> bool:
    result = await conn.execute(
        update(_t)
        .where(and_(_t.c.id == service_id, _t.c.owner_login == owner_login))
        .values(name=name, url=url, mcp_profile_id=mcp_profile_id, updated_at=func.now())
    )
    return (result.rowcount or 0) > 0


async def delete_service(conn: AsyncConnection, owner_login: str, service_id: str) -> bool:
    result = await conn.execute(
        delete(_t).where(and_(_t.c.id == service_id, _t.c.owner_login == owner_login))
    )
    return (result.rowcount or 0) > 0
