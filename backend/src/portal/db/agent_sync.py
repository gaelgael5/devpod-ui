"""Persistance de l'empreinte de config agents par workspace (workspace_agent_sync)."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import workspace_agent_sync


async def get_config_hash(conn: AsyncConnection, ws_id: str) -> str | None:
    """Empreinte de la dernière config agents livrée à ce workspace, ou None."""
    row = (
        await conn.execute(
            select(workspace_agent_sync.c.config_hash).where(workspace_agent_sync.c.ws_id == ws_id)
        )
    ).first()
    return str(row[0]) if row else None


async def upsert_config_hash(conn: AsyncConnection, ws_id: str, config_hash: str) -> None:
    """Enregistre (ou remplace) l'empreinte livrée pour ce workspace."""
    await conn.execute(
        pg_insert(workspace_agent_sync)
        .values(ws_id=ws_id, config_hash=config_hash)
        .on_conflict_do_update(
            index_elements=[workspace_agent_sync.c.ws_id],
            set_={"config_hash": config_hash, "updated_at": func.now()},
        )
    )


async def delete_config_hash(conn: AsyncConnection, ws_id: str) -> None:
    """Oublie l'empreinte (suppression du workspace) — un ws_id réutilisé re-livre."""
    await conn.execute(delete(workspace_agent_sync).where(workspace_agent_sync.c.ws_id == ws_id))
