"""Accès en base aux templates de création de workspace.

Galerie préparée par l'admin : un template fige les recettes, agents, profil
devcontainer, limite mémoire et clef SSH — l'utilisateur ne saisit que le nom
et le repo git. `published` gouverne la visibilité côté utilisateur.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import WorkspaceTemplate, WorkspaceTemplateSpec
from .tables import workspace_templates


def _row_to_template(row: dict[str, Any]) -> WorkspaceTemplate:
    return WorkspaceTemplate(
        slug=row["slug"],
        label=row["label"] or "",
        description=row["description"] or "",
        published=bool(row["published"]),
        spec=WorkspaceTemplateSpec.model_validate(row["spec"] or {}),
    )


async def list_templates(
    conn: AsyncConnection, *, published_only: bool = False
) -> list[WorkspaceTemplate]:
    stmt = select(workspace_templates).order_by(workspace_templates.c.label)
    if published_only:
        stmt = stmt.where(workspace_templates.c.published.is_(True))
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row_to_template(dict(r)) for r in rows]


async def get_template(slug: str, conn: AsyncConnection) -> WorkspaceTemplate | None:
    row = (
        (await conn.execute(select(workspace_templates).where(workspace_templates.c.slug == slug)))
        .mappings()
        .first()
    )
    return _row_to_template(dict(row)) if row else None


async def upsert_template(template: WorkspaceTemplate, conn: AsyncConnection) -> None:
    values = {
        "slug": template.slug,
        "label": template.label,
        "description": template.description,
        "published": template.published,
        "spec": template.spec.model_dump(),
    }
    stmt = pg_insert(workspace_templates).values(**values)
    await conn.execute(
        stmt.on_conflict_do_update(
            index_elements=[workspace_templates.c.slug],
            set_={k: v for k, v in values.items() if k != "slug"},
        )
    )


async def delete_template(slug: str, conn: AsyncConnection) -> bool:
    result = await conn.execute(
        delete(workspace_templates).where(workspace_templates.c.slug == slug)
    )
    return bool(result.rowcount)
