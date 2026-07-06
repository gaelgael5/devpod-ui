"""Accès DB aux types d'agents workspace (spec 35)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import agent_type

_COLS = [
    agent_type.c.id,
    agent_type.c.label,
    agent_type.c.filename,
    agent_type.c.template,
    agent_type.c.target_path,
    agent_type.c.mode,
    agent_type.c.enabled,
    agent_type.c.created_at,
    agent_type.c.updated_at,
]


async def list_agent_types(
    conn: AsyncConnection, *, enabled_only: bool = False
) -> list[dict[str, Any]]:
    q = select(*_COLS).order_by(agent_type.c.id)
    if enabled_only:
        q = q.where(agent_type.c.enabled.is_(True))
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def get_agent_type(conn: AsyncConnection, agent_id: str) -> dict[str, Any] | None:
    q = select(*_COLS).where(agent_type.c.id == agent_id)
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def insert_agent_type(
    conn: AsyncConnection,
    *,
    id: str,
    label: str,
    filename: str,
    template: str,
    target_path: str,
    mode: str = "replace",
    enabled: bool = True,
) -> None:
    await conn.execute(
        insert(agent_type).values(
            id=id,
            label=label,
            filename=filename,
            template=template,
            target_path=target_path,
            mode=mode,
            enabled=enabled,
        )
    )


async def update_agent_type(
    conn: AsyncConnection,
    agent_id: str,
    *,
    label: str,
    filename: str,
    template: str,
    target_path: str,
    enabled: bool,
    mode: str | None = None,
) -> bool:
    values: dict[str, Any] = {
        "label": label,
        "filename": filename,
        "template": template,
        "target_path": target_path,
        "enabled": enabled,
        "updated_at": func.now(),
    }
    # mode omis (None) = inchangé — les appelants qui ne le gèrent pas encore
    # (avant le câblage du DTO) ne doivent pas écraser la valeur existante.
    if mode is not None:
        values["mode"] = mode
    q = (
        update(agent_type)
        .where(agent_type.c.id == agent_id)
        .values(**values)
        .returning(agent_type.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def delete_agent_type(conn: AsyncConnection, agent_id: str) -> bool:
    q = delete(agent_type).where(agent_type.c.id == agent_id).returning(agent_type.c.id)
    return (await conn.execute(q)).first() is not None
