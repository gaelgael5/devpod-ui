"""Persistance workspace_status (table workspace_status) — remplace routes/*.json."""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import workspace_status


async def upsert_status_db(
    ws_id: str,
    status: str,
    conn: AsyncConnection,
    login: str = "",
    **extra: Any,
) -> None:
    existing = (
        await conn.execute(
            select(workspace_status.c.ws_id).where(workspace_status.c.ws_id == ws_id)
        )
    ).scalar_one_or_none()

    vals: dict[str, Any] = {
        "ws_id": ws_id,
        "status": status,
        "login": login,
        "host_port": extra.get("host_port"),
        "host_type": extra.get("host_type"),
        "host_name": extra.get("host_name"),
        "url": extra.get("url"),
        "hostname": extra.get("hostname"),
        "returncode": extra.get("returncode"),
        "error": extra.get("error"),
    }
    if existing is None:
        await conn.execute(insert(workspace_status).values(**vals))
    else:
        update_vals = {k: v for k, v in vals.items() if k != "ws_id"}
        update_vals["updated_at"] = func.now()
        await conn.execute(
            update(workspace_status)
            .where(workspace_status.c.ws_id == ws_id)
            .values(**update_vals)
        )


async def get_status_db(ws_id: str, conn: AsyncConnection) -> dict[str, Any] | None:
    row = (
        await conn.execute(
            select(workspace_status).where(workspace_status.c.ws_id == ws_id)
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def list_by_login_db(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            select(workspace_status).where(workspace_status.c.login == login)
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def list_running_db(conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            select(workspace_status).where(workspace_status.c.status == "running")
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def delete_status_db(ws_id: str, conn: AsyncConnection) -> None:
    await conn.execute(
        delete(workspace_status).where(workspace_status.c.ws_id == ws_id)
    )
