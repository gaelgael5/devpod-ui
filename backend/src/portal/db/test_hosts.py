"""Association VM de test ↔ workspace propriétaire."""
from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import workspace_test_hosts as _t

_ALIAS_RE = re.compile(r"^test([0-9]+)$")


def next_test_alias(used: Iterable[str]) -> str:
    """Plus petit alias `testN` (N ≥ 1) non présent dans `used`.

    Réutilise les numéros libérés (liste contiguë) ; les valeurs hors forme `testN`
    sont ignorées.
    """
    taken: set[int] = set()
    for value in used:
        m = _ALIAS_RE.match(value or "")
        if m:
            taken.add(int(m.group(1)))
    n = 1
    while n in taken:
        n += 1
    return f"test{n}"


async def assign_test_host(
    login: str, workspace_name: str, host_name: str, alias: str, conn: AsyncConnection
) -> None:
    """Associe un host de test à un workspace avec son alias (idempotent)."""
    stmt = (
        pg_insert(_t)
        .values(
            login=login,
            workspace_name=workspace_name,
            host_name=host_name,
            alias=alias,
        )
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


async def list_test_hosts_detailed(
    login: str, workspace_name: str, conn: AsyncConnection
) -> list[tuple[str, str]]:
    """(host_name, alias) des hosts de test d'un workspace, triés par numéro d'alias."""
    rows = (
        await conn.execute(
            select(_t.c.host_name, _t.c.alias).where(
                (_t.c.login == login) & (_t.c.workspace_name == workspace_name)
            )
        )
    ).all()

    def _alias_num(alias: str | None) -> int:
        m = _ALIAS_RE.match(alias or "")
        return int(m.group(1)) if m else 1_000_000

    pairs = [(r[0], r[1] or "") for r in rows]
    return sorted(pairs, key=lambda p: _alias_num(p[1]))


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
