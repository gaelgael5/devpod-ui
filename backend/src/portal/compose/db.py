"""Couche DB SQLAlchemy Core de la galerie compose."""

from __future__ import annotations

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.tables import compose_deployment, compose_deployment_log, compose_template
from .models import ComposeDeployment, ComposeParam, ComposeTemplate


def _row_to_template(row: RowMapping) -> ComposeTemplate:
    return ComposeTemplate(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        tags=list(row["tags"] or []),
        version=row["version"],
        compose_content=row["compose_content"],
        parameters=[ComposeParam.model_validate(p) for p in (row["parameters"] or [])],
        source=row["source"],
        extra_files=dict(row.get("extra_files") or {}),
        message_key=row.get("message_key"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


async def create_template(conn: AsyncConnection, tpl: ComposeTemplate) -> None:
    await conn.execute(
        insert(compose_template).values(
            id=tpl.id,
            name=tpl.name,
            description=tpl.description,
            tags=tpl.tags,
            version=tpl.version,
            compose_content=tpl.compose_content,
            parameters=[p.model_dump() for p in tpl.parameters],
            source=tpl.source,
            extra_files=tpl.extra_files,
            message_key=tpl.message_key,
        )
    )


async def get_template(conn: AsyncConnection, template_id: str) -> ComposeTemplate | None:
    row = (
        (await conn.execute(select(compose_template).where(compose_template.c.id == template_id)))
        .mappings()
        .first()
    )
    return _row_to_template(row) if row else None


async def list_templates(conn: AsyncConnection, tag: str | None = None) -> list[ComposeTemplate]:
    stmt = select(compose_template).order_by(compose_template.c.name)
    if tag is not None:
        stmt = stmt.where(compose_template.c.tags.any(tag))
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row_to_template(r) for r in rows]


async def update_template(conn: AsyncConnection, tpl: ComposeTemplate) -> None:
    await conn.execute(
        update(compose_template)
        .where(compose_template.c.id == tpl.id)
        .values(
            name=tpl.name,
            description=tpl.description,
            tags=tpl.tags,
            version=tpl.version,
            compose_content=tpl.compose_content,
            parameters=[p.model_dump() for p in tpl.parameters],
            source=tpl.source,
            extra_files=tpl.extra_files,
            message_key=tpl.message_key,
            updated_at=func.now(),
        )
    )


async def delete_template(conn: AsyncConnection, template_id: str) -> None:
    await conn.execute(delete(compose_template).where(compose_template.c.id == template_id))


async def count_deployments_for_template(conn: AsyncConnection, template_id: str) -> int:
    """Nombre de déploiements actifs référençant ce template (pour garder le FK cohérent)."""
    row = (
        await conn.execute(
            select(func.count())
            .select_from(compose_deployment)
            .where(compose_deployment.c.template_id == template_id)
        )
    ).scalar()
    return row or 0


def _row_to_deployment(row: RowMapping) -> ComposeDeployment:
    return ComposeDeployment(
        uid=row["uid"],
        id=row["id"],
        template_id=row["template_id"],
        template_version=row["template_version"],
        node_id=row["node_id"],
        owner_login=row["owner_login"],
        env_values=dict(row["env_values"] or {}),
        host_ports=list(row["host_ports"] or []),
        status=row["status"],
        last_error=row.get("last_error"),
        message_id=row.get("message_id"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


async def create_deployment(conn: AsyncConnection, dep: ComposeDeployment) -> None:
    await conn.execute(
        insert(compose_deployment).values(
            uid=dep.uid,
            id=dep.id,
            template_id=dep.template_id,
            template_version=dep.template_version,
            node_id=dep.node_id,
            owner_login=dep.owner_login,
            env_values=dep.env_values,
            host_ports=dep.host_ports,
            status=dep.status,
            last_error=dep.last_error,
        )
    )


async def get_deployment(conn: AsyncConnection, uid: str) -> ComposeDeployment | None:
    """Cherche un déploiement par son UUID (PK)."""
    row = (
        (await conn.execute(select(compose_deployment).where(compose_deployment.c.uid == uid)))
        .mappings()
        .first()
    )
    return _row_to_deployment(row) if row else None


async def get_deployment_by_slug(conn: AsyncConnection, slug: str) -> ComposeDeployment | None:
    """Cherche un déploiement par son slug (colonne id, identifiant user-facing)."""
    row = (
        (await conn.execute(select(compose_deployment).where(compose_deployment.c.id == slug)))
        .mappings()
        .first()
    )
    return _row_to_deployment(row) if row else None


async def get_deployment_by_name_node(
    conn: AsyncConnection, name: str, node_id: str
) -> ComposeDeployment | None:
    """Cherche un déploiement par son slug + nœud (contrainte d'unicité métier)."""
    row = (
        (
            await conn.execute(
                select(compose_deployment).where(
                    (compose_deployment.c.id == name) & (compose_deployment.c.node_id == node_id)
                )
            )
        )
        .mappings()
        .first()
    )
    return _row_to_deployment(row) if row else None


async def list_deployments(
    conn: AsyncConnection, *, owner_login: str | None
) -> list[ComposeDeployment]:
    stmt = select(compose_deployment).order_by(compose_deployment.c.created_at.desc())
    if owner_login is not None:
        stmt = stmt.where(compose_deployment.c.owner_login == owner_login)
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row_to_deployment(r) for r in rows]


async def list_deployments_for_node(conn: AsyncConnection, node_id: str) -> list[ComposeDeployment]:
    """Tous les déploiements sur un nœud donné, triés par date décroissante."""
    rows = (
        (
            await conn.execute(
                select(compose_deployment)
                .where(compose_deployment.c.node_id == node_id)
                .order_by(compose_deployment.c.created_at.desc())
            )
        )
        .mappings()
        .all()
    )
    return [_row_to_deployment(r) for r in rows]


async def update_deployment_status(
    conn: AsyncConnection, uid: str, status: str, last_error: str | None = None
) -> None:
    await conn.execute(
        update(compose_deployment)
        .where(compose_deployment.c.uid == uid)
        .values(status=status, last_error=last_error, updated_at=func.now())
    )


async def update_deployment_message_id(
    conn: AsyncConnection, uid: str, message_id: int | None
) -> None:
    await conn.execute(
        update(compose_deployment)
        .where(compose_deployment.c.uid == uid)
        .values(message_id=message_id, updated_at=func.now())
    )


async def delete_deployment(conn: AsyncConnection, uid: str) -> None:
    await conn.execute(delete(compose_deployment).where(compose_deployment.c.uid == uid))


async def used_ports_on_node(conn: AsyncConnection, node_id: str) -> set[int]:
    """Tous les ports host déjà réservés sur ce nœud (tous déploiements confondus)."""
    rows = (
        await conn.execute(
            select(compose_deployment.c.host_ports).where(compose_deployment.c.node_id == node_id)
        )
    ).all()
    result: set[int] = set()
    for (hp,) in rows:
        result |= set(hp or [])
    return result


async def conflicting_ports(conn: AsyncConnection, node_id: str, ports: list[int]) -> set[int]:
    """Ports déjà réservés par un autre déploiement sur ce nœud (node-wide, tous owners)."""
    if not ports:
        return set()
    rows = (
        await conn.execute(
            select(compose_deployment.c.host_ports).where(
                (compose_deployment.c.node_id == node_id)
                & compose_deployment.c.host_ports.overlap(ports)
            )
        )
    ).all()
    occupied: set[int] = set()
    requested = set(ports)
    for (hp,) in rows:
        occupied |= requested & set(hp or [])
    return occupied


async def persist_op_log(conn: AsyncConnection, uid: str, operation: str, content: str) -> None:
    await conn.execute(
        insert(compose_deployment_log).values(
            deployment_id=uid,
            operation=operation,
            content=content,
            finished_at=func.now(),
        )
    )
