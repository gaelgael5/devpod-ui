"""CRUD base de données pour les groupes de workspaces."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import workspace_group, workspaces

_GROUP_NAME_MAX = 50


def _validate_group_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Le nom du groupe ne peut pas être vide")
    if len(name) > _GROUP_NAME_MAX:
        raise ValueError(f"Le nom du groupe ne peut pas dépasser {_GROUP_NAME_MAX} caractères")
    return name


async def list_groups(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                select(workspace_group)
                .where(workspace_group.c.login == login)
                .order_by(workspace_group.c.name)
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def get_groups_for_workspace(
    login: str, workspace_name: str, conn: AsyncConnection
) -> list[str]:
    """Groupes d'un workspace (tableau `workspaces.groups`) ; [] si absent."""
    row = (
        await conn.execute(
            select(workspaces.c.groups).where(
                workspaces.c.login == login,
                workspaces.c.name == workspace_name,
            )
        )
    ).scalar_one_or_none()
    return list(row or [])


async def list_workspace_names_in_group(
    login: str, group_name: str, conn: AsyncConnection
) -> list[str]:
    """Noms des workspaces du user portant `group_name` dans leur tableau `groups`."""
    rows = (
        (
            await conn.execute(
                select(workspaces.c.name).where(
                    workspaces.c.login == login,
                    text(":gname = ANY(groups)").bindparams(gname=group_name),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def create_group(login: str, name: str, conn: AsyncConnection) -> dict[str, Any]:
    name = _validate_group_name(name)
    result = await conn.execute(
        insert(workspace_group)
        .values(login=login, name=name)
        .returning(workspace_group.c.id, workspace_group.c.name, workspace_group.c.created_at)
    )
    row = result.mappings().one()
    return dict(row)


async def rename_group(
    group_id: int, login: str, new_name: str, conn: AsyncConnection
) -> dict[str, Any] | None:
    new_name = _validate_group_name(new_name)

    existing = (
        await conn.execute(
            select(workspace_group.c.name).where(
                workspace_group.c.id == group_id,
                workspace_group.c.login == login,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return None

    old_name = existing

    # Renommer dans workspace_group
    result = await conn.execute(
        update(workspace_group)
        .where(workspace_group.c.id == group_id, workspace_group.c.login == login)
        .values(name=new_name)
        .returning(workspace_group.c.id, workspace_group.c.name, workspace_group.c.created_at)
    )
    row = result.mappings().one()

    # Mettre à jour les tableaux groups dans tous les workspaces du user
    await conn.execute(
        update(workspaces)
        .where(
            workspaces.c.login == login,
            text(":old = ANY(groups)").bindparams(old=old_name),
        )
        .values(
            groups=func.array_replace(workspaces.c.groups, old_name, new_name),
            updated_at=func.now(),
        )
    )

    return dict(row)


async def delete_group(group_id: int, login: str, conn: AsyncConnection) -> bool:
    existing = (
        await conn.execute(
            select(workspace_group.c.name).where(
                workspace_group.c.id == group_id,
                workspace_group.c.login == login,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return False

    group_name = existing

    # Refuser si des workspaces appartiennent encore à ce groupe
    ws_count = (
        await conn.execute(
            select(func.count())
            .select_from(workspaces)
            .where(
                workspaces.c.login == login,
                text(":gname = ANY(groups)").bindparams(gname=group_name),
            )
        )
    ).scalar_one()
    if ws_count > 0:
        raise ValueError(
            f"Le groupe «{group_name}» contient encore {ws_count} workspace(s)"
            " — retirez-les d'abord"
        )

    await conn.execute(
        delete(workspace_group).where(
            workspace_group.c.id == group_id,
            workspace_group.c.login == login,
        )
    )
    return True


async def set_workspace_groups(
    login: str,
    workspace_name: str,
    group_names: list[str],
    conn: AsyncConnection,
) -> bool:
    """Remplace les groupes d'un workspace. Vérifie que tous les noms existent pour ce user."""
    if group_names:
        existing_names = set(
            (
                await conn.execute(
                    select(workspace_group.c.name).where(
                        workspace_group.c.login == login,
                        workspace_group.c.name.in_(group_names),
                    )
                )
            )
            .scalars()
            .all()
        )
        unknown = set(group_names) - existing_names
        if unknown:
            raise ValueError(f"Groupes inconnus : {', '.join(sorted(unknown))}")

    result = await conn.execute(
        update(workspaces)
        .where(workspaces.c.login == login, workspaces.c.name == workspace_name)
        .values(groups=list(group_names), updated_at=func.now())
    )
    return result.rowcount > 0
