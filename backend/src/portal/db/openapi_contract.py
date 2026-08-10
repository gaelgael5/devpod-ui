"""Couche DB des contrats OpenAPI (`openapi_contract`).

Contrats stockés globalement (réutilisables entre automates). La transaction est
toujours ouverte par l'appelant ; ce module n'y committe jamais.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import openapi_contract as _c


async def create(
    conn: AsyncConnection,
    *,
    label: str,
    raw_spec: dict[str, Any],
    version: str = "",
    source_url: str | None = None,
    category: str = "",
) -> dict[str, Any]:
    """Crée un contrat et retourne la ligne insérée."""
    contract_id = uuid.uuid4().hex
    stmt = (
        insert(_c)
        .values(
            id=contract_id,
            label=label,
            category=category,
            source_url=source_url,
            version=version,
            raw_spec=raw_spec,
        )
        .returning(_c)
    )
    return dict((await conn.execute(stmt)).mappings().one())


async def update_spec(
    conn: AsyncConnection,
    contract_id: str,
    *,
    label: str | None = None,
    raw_spec: dict[str, Any] | None = None,
    version: str | None = None,
    source_url: str | None = None,
    category: str | None = None,
) -> dict[str, Any] | None:
    """Met à jour un contrat (champs fournis uniquement). None si absent."""
    values: dict[str, Any] = {"updated_at": func.now()}
    if label is not None:
        values["label"] = label
    if raw_spec is not None:
        values["raw_spec"] = raw_spec
    if version is not None:
        values["version"] = version
    if source_url is not None:
        values["source_url"] = source_url
    if category is not None:
        values["category"] = category
    stmt = update(_c).where(_c.c.id == contract_id).values(**values).returning(_c)
    row = (await conn.execute(stmt)).mappings().first()
    return dict(row) if row is not None else None


async def get(conn: AsyncConnection, contract_id: str) -> dict[str, Any] | None:
    row = (await conn.execute(select(_c).where(_c.c.id == contract_id))).mappings().first()
    return dict(row) if row is not None else None


async def list_all(conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = (await conn.execute(select(_c).order_by(_c.c.category, _c.c.label))).mappings().all()
    return [dict(r) for r in rows]


async def delete_contract(conn: AsyncConnection, contract_id: str) -> bool:
    """Supprime un contrat. Retourne False si absent. Lève si référencé (FK RESTRICT)."""
    result = await conn.execute(delete(_c).where(_c.c.id == contract_id))
    return bool(result.rowcount)
