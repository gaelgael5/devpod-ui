from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import mcp_backend

_BACKEND_COLS = [
    mcp_backend.c.id,
    mcp_backend.c.owner_login,
    mcp_backend.c.namespace,
    mcp_backend.c.name,
    mcp_backend.c.url,
    mcp_backend.c.transport,
    mcp_backend.c.enabled,
    mcp_backend.c.created_at,
    mcp_backend.c.updated_at,
]


async def insert_backend(
    conn: AsyncConnection,
    *,
    id: str,
    owner_login: str,
    namespace: str,
    name: str,
    url: str,
    transport: str,
) -> None:
    await conn.execute(
        insert(mcp_backend).values(
            id=id,
            owner_login=owner_login,
            namespace=namespace,
            name=name,
            url=url,
            transport=transport,
        )
    )


async def list_backends(conn: AsyncConnection, owner_login: str) -> list[dict[str, Any]]:
    q = (
        select(*_BACKEND_COLS)
        .where(mcp_backend.c.owner_login == owner_login)
        .order_by(mcp_backend.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def get_backend(
    conn: AsyncConnection, owner_login: str, backend_id: str
) -> dict[str, Any] | None:
    q = select(*_BACKEND_COLS).where(
        mcp_backend.c.id == backend_id,
        mcp_backend.c.owner_login == owner_login,
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def update_backend(
    conn: AsyncConnection,
    owner_login: str,
    backend_id: str,
    *,
    name: str,
    url: str,
    transport: str,
    enabled: bool,
) -> bool:
    q = (
        update(mcp_backend)
        .where(mcp_backend.c.id == backend_id, mcp_backend.c.owner_login == owner_login)
        .values(name=name, url=url, transport=transport, enabled=enabled, updated_at=func.now())
        .returning(mcp_backend.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def delete_backend(conn: AsyncConnection, owner_login: str, backend_id: str) -> bool:
    q = (
        delete(mcp_backend)
        .where(mcp_backend.c.id == backend_id, mcp_backend.c.owner_login == owner_login)
        .returning(mcp_backend.c.id)
    )
    return (await conn.execute(q)).first() is not None
