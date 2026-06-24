"""Association VM de test ↔ workspace propriétaire."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import workspace_test_hosts as _t


async def assign_test_host(
    login: str, workspace_name: str, host_name: str, conn: AsyncConnection
) -> None:
    """Associe un host de test à un workspace (idempotent)."""
    stmt = (
        pg_insert(_t)
        .values(login=login, workspace_name=workspace_name, host_name=host_name)
        .on_conflict_do_nothing(constraint="uq_wth_login_ws_host")
    )
    await conn.execute(stmt)


async def list_test_hosts_for_workspace(
    login: str, workspace_name: str, conn: AsyncConnection
) -> list[str]:
    """Noms des hosts de test attachés à un workspace."""
    rows = (
        await conn.execute(
            select(_t.c.host_name).where(
                (_t.c.login == login) & (_t.c.workspace_name == workspace_name)
            )
        )
    ).scalars().all()
    return list(rows)


async def workspace_for_host(
    host_name: str, conn: AsyncConnection
) -> tuple[str, str] | None:
    """(login, workspace_name) propriétaire d'un host de test, ou None."""
    row = (
        await conn.execute(
            select(_t.c.login, _t.c.workspace_name).where(_t.c.host_name == host_name)
        )
    ).mappings().first()
    return (row["login"], row["workspace_name"]) if row else None


async def remove_test_host(host_name: str, conn: AsyncConnection) -> None:
    """Détache un host de test (toutes associations confondues)."""
    await conn.execute(delete(_t).where(_t.c.host_name == host_name))
