"""Couche DB SQLAlchemy Core de la galerie compose."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.tables import compose_deployment, compose_deployment_log, compose_template  # noqa: F401
from .models import ComposeDeployment, ComposeParam, ComposeTemplate  # noqa: F401


def _row_to_template(row: Any) -> ComposeTemplate:
    return ComposeTemplate(
        id=row["id"], name=row["name"], description=row["description"],
        tags=list(row["tags"] or []), version=row["version"],
        compose_content=row["compose_content"],
        parameters=[ComposeParam.model_validate(p) for p in (row["parameters"] or [])],
        source=row["source"], created_at=row.get("created_at"), updated_at=row.get("updated_at"),
    )


async def create_template(conn: AsyncConnection, tpl: ComposeTemplate) -> None:
    await conn.execute(
        insert(compose_template).values(
            id=tpl.id, name=tpl.name, description=tpl.description, tags=tpl.tags,
            version=tpl.version, compose_content=tpl.compose_content,
            parameters=[p.model_dump() for p in tpl.parameters], source=tpl.source,
        )
    )


async def get_template(conn: AsyncConnection, template_id: str) -> ComposeTemplate | None:
    row = (
        await conn.execute(select(compose_template).where(compose_template.c.id == template_id))
    ).mappings().first()
    return _row_to_template(row) if row else None


async def list_templates(conn: AsyncConnection, tag: str | None = None) -> list[ComposeTemplate]:
    stmt = select(compose_template).order_by(compose_template.c.name)
    if tag is not None:
        stmt = stmt.where(compose_template.c.tags.any(tag))
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row_to_template(r) for r in rows]


async def update_template(conn: AsyncConnection, tpl: ComposeTemplate) -> None:
    await conn.execute(
        update(compose_template).where(compose_template.c.id == tpl.id).values(
            name=tpl.name, description=tpl.description, tags=tpl.tags, version=tpl.version,
            compose_content=tpl.compose_content,
            parameters=[p.model_dump() for p in tpl.parameters], source=tpl.source,
            updated_at=func.now(),
        )
    )


async def delete_template(conn: AsyncConnection, template_id: str) -> None:
    await conn.execute(delete(compose_template).where(compose_template.c.id == template_id))
