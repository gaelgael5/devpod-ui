"""Persistance workspace_status (table workspace_status) — remplace routes/*.json."""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import workspace_status


async def upsert_status_db(
    ws_id: str,
    status: str,
    conn: AsyncConnection,
    login: str = "",
    **extra: Any,
) -> None:
    """Upsert atomique via INSERT … ON CONFLICT (bug 010).

    Le pattern « SELECT pour décider INSERT ou UPDATE » n'est pas atomique :
    deux transactions concurrentes en READ COMMITTED voient chacune l'absence
    de ligne → double INSERT → UniqueViolation. L'upsert natif Postgres rend
    l'opération idempotente sous concurrence.
    """
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
    set_vals: dict[str, Any] = {k: v for k, v in vals.items() if k != "ws_id"}
    set_vals["updated_at"] = func.now()
    await conn.execute(
        pg_insert(workspace_status)
        .values(**vals)
        .on_conflict_do_update(
            index_elements=[workspace_status.c.ws_id],
            set_=set_vals,
        )
    )


async def update_status_if_exists_db(
    ws_id: str,
    status: str,
    conn: AsyncConnection,
    login: str = "",
    **extra: Any,
) -> bool:
    """Met à jour le statut UNIQUEMENT si la ligne existe déjà — jamais d'INSERT.

    Épitaphe anti-résurrection (bug 003/004) : un `up` tardif ne doit pas recréer
    une ligne qu'un `delete` concurrent vient de supprimer. Le WHERE ws_id rend la
    garde atomique côté DB (pas de fenêtre TOCTOU comme un get-puis-upsert).

    Retourne True si une ligne a été mise à jour, False si la ligne est absente.
    """
    update_vals: dict[str, Any] = {
        "status": status,
        "login": login,
        "host_port": extra.get("host_port"),
        "host_type": extra.get("host_type"),
        "host_name": extra.get("host_name"),
        "url": extra.get("url"),
        "hostname": extra.get("hostname"),
        "returncode": extra.get("returncode"),
        "error": extra.get("error"),
        "updated_at": func.now(),
    }
    result = await conn.execute(
        update(workspace_status)
        .where(workspace_status.c.ws_id == ws_id)
        .values(**update_vals)
    )
    return (result.rowcount or 0) > 0


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
