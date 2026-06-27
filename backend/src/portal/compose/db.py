"""Couche DB SQLAlchemy Core de la galerie compose."""
from __future__ import annotations

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.tables import compose_deployment, compose_deployment_log, compose_template
from .models import ComposeDeployment, ComposeParam, ComposeTemplate


def _row_to_template(row: RowMapping) -> ComposeTemplate:
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


def _row_to_deployment(row: RowMapping) -> ComposeDeployment:
    return ComposeDeployment(
        id=row["id"], template_id=row["template_id"], template_version=row["template_version"],
        node_id=row["node_id"], owner_login=row["owner_login"],
        env_values=dict(row["env_values"] or {}), host_ports=list(row["host_ports"] or []),
        status=row["status"], last_error=row.get("last_error"),
        created_at=row.get("created_at"), updated_at=row.get("updated_at"),
    )


async def create_deployment(conn: AsyncConnection, dep: ComposeDeployment) -> None:
    await conn.execute(
        insert(compose_deployment).values(
            id=dep.id, template_id=dep.template_id, template_version=dep.template_version,
            node_id=dep.node_id, owner_login=dep.owner_login, env_values=dep.env_values,
            host_ports=dep.host_ports, status=dep.status, last_error=dep.last_error,
        )
    )


async def get_deployment(conn: AsyncConnection, deployment_id: str) -> ComposeDeployment | None:
    row = (
        await conn.execute(
            select(compose_deployment).where(compose_deployment.c.id == deployment_id)
        )
    ).mappings().first()
    return _row_to_deployment(row) if row else None


async def list_deployments(
    conn: AsyncConnection, *, owner_login: str | None
) -> list[ComposeDeployment]:
    stmt = select(compose_deployment).order_by(compose_deployment.c.created_at.desc())
    if owner_login is not None:
        stmt = stmt.where(compose_deployment.c.owner_login == owner_login)
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row_to_deployment(r) for r in rows]


async def update_deployment_status(
    conn: AsyncConnection, deployment_id: str, status: str, last_error: str | None = None
) -> None:
    await conn.execute(
        update(compose_deployment).where(compose_deployment.c.id == deployment_id).values(
            status=status, last_error=last_error, updated_at=func.now()
        )
    )


async def delete_deployment(conn: AsyncConnection, deployment_id: str) -> None:
    await conn.execute(
        delete(compose_deployment).where(compose_deployment.c.id == deployment_id)
    )


async def conflicting_ports(
    conn: AsyncConnection, node_id: str, ports: list[int]
) -> set[int]:
    """Ports déjà réservés par un autre déploiement sur ce nœud (node-wide, tous owners)."""
    if not ports:
        return set()
    rows = (
        await conn.execute(
            select(compose_deployment.c.host_ports).where(
                (compose_deployment.c.node_id == node_id)
                & compose_deployment.c.host_ports.op("&&")(ports)
            )
        )
    ).all()
    occupied: set[int] = set()
    requested = set(ports)
    for (hp,) in rows:
        occupied |= requested & set(hp or [])
    return occupied


async def persist_op_log(
    conn: AsyncConnection, deployment_id: str, operation: str, content: str
) -> None:
    await conn.execute(
        insert(compose_deployment_log).values(
            deployment_id=deployment_id, operation=operation, content=content,
            finished_at=func.now(),
        )
    )
