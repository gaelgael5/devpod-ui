"""Association VM de test ↔ workspace propriétaire."""
from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import test_host_links as _links
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


async def host_full_info(
    host_name: str, conn: AsyncConnection
) -> tuple[str, str, str] | None:
    """(login, workspace_name, alias) pour un host de test, ou None."""
    row = (
        await conn.execute(
            select(_t.c.login, _t.c.workspace_name, _t.c.alias).where(
                _t.c.host_name == host_name
            )
        )
    ).mappings().first()
    return (row["login"], row["workspace_name"], row["alias"] or "") if row else None


async def get_test_host_message_id(
    host_name: str, conn: AsyncConnection
) -> int | None:
    """Retourne le message_id associé à un host de test, ou None."""
    return (
        await conn.execute(
            select(_t.c.message_id).where(_t.c.host_name == host_name)
        )
    ).scalar_one_or_none()


async def set_test_host_message_id(
    host_name: str, message_id: int | None, conn: AsyncConnection
) -> None:
    """Enregistre le message_id associé à un host de test."""
    await conn.execute(
        update(_t).where(_t.c.host_name == host_name).values(message_id=message_id)
    )


async def remove_test_host(host_name: str, conn: AsyncConnection) -> None:
    """Détache un host de test (toutes associations confondues)."""
    await conn.execute(delete(_t).where(_t.c.host_name == host_name))


# ─── Liens (clé → URL) d'un serveur de test (menu ⋮ du host) ─────────────────


async def _test_host_id(
    login: str, workspace_name: str, host_name: str, conn: AsyncConnection
) -> int | None:
    """id de l'association (login, workspace, host) — garde d'appartenance incluse."""
    return (
        await conn.execute(
            select(_t.c.id).where(
                (_t.c.login == login)
                & (_t.c.workspace_name == workspace_name)
                & (_t.c.host_name == host_name)
            )
        )
    ).scalar_one_or_none()


async def list_test_host_links(
    login: str, workspace_name: str, host_name: str, conn: AsyncConnection
) -> list[dict[str, str]] | None:
    """Liens du host, triés par clé. None si le host n'appartient pas au couple login/ws."""
    host_id = await _test_host_id(login, workspace_name, host_name, conn)
    if host_id is None:
        return None
    rows = (
        await conn.execute(
            select(_links.c.key, _links.c.url)
            .where(_links.c.test_host_id == host_id)
            .order_by(_links.c.key)
        )
    ).all()
    return [{"key": r[0], "url": r[1]} for r in rows]


async def upsert_test_host_link(
    login: str, workspace_name: str, host_name: str, key: str, url: str, conn: AsyncConnection
) -> bool:
    """Enregistre (ou remplace) un lien. False si le host n'appartient pas au couple login/ws."""
    host_id = await _test_host_id(login, workspace_name, host_name, conn)
    if host_id is None:
        return False
    await conn.execute(
        pg_insert(_links)
        .values(test_host_id=host_id, key=key, url=url)
        .on_conflict_do_update(constraint="uq_thl_host_key", set_={"url": url})
    )
    return True


async def delete_test_host_link(
    login: str, workspace_name: str, host_name: str, key: str, conn: AsyncConnection
) -> bool:
    """Supprime un lien. True si une ligne a été supprimée."""
    host_id = await _test_host_id(login, workspace_name, host_name, conn)
    if host_id is None:
        return False
    result = await conn.execute(
        delete(_links).where(
            (_links.c.test_host_id == host_id) & (_links.c.key == key)
        )
    )
    return (result.rowcount or 0) > 0
