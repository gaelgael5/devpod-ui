from __future__ import annotations

from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import mcp_audit_log as al


async def record(
    conn: AsyncConnection,
    *,
    apikey_id: str | None,
    owner_login: str | None,
    namespaced_name: str | None,
    backend_id: str | None,
    backend_key_id: str | None,
    latency_ms: int | None,
    status: str,
    error: str | None,
) -> None:
    """Enregistre une entrée dans le journal d'audit MCP."""
    await conn.execute(
        insert(al).values(
            apikey_id=apikey_id,
            owner_login=owner_login,
            namespaced_name=namespaced_name,
            backend_id=backend_id,
            backend_key_id=backend_key_id,
            latency_ms=latency_ms,
            status=status,
            error=error,
        )
    )


async def list_for_owner(
    conn: AsyncConnection, owner_login: str, limit: int = 100
) -> list[dict[str, Any]]:
    """Retourne les entrées d'audit d'un utilisateur, ordre chronologique inversé."""
    q = (
        select(al)
        .where(al.c.owner_login == owner_login)
        .order_by(al.c.ts.desc())
        .limit(limit)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]
