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
    login: str,
    workspace_name: str,
    host_name: str,
    alias: str,
    conn: AsyncConnection,
    *,
    shared_from: str | None = None,
) -> None:
    """Associe un host de test à un workspace avec son alias (idempotent).

    `shared_from` NULL = ligne du workspace PROPRIÉTAIRE ; non-NULL (nom du
    workspace d'origine) = ligne de PARTAGE (accès SSH seul, pas de cycle de vie).
    """
    stmt = (
        pg_insert(_t)
        .values(
            login=login,
            workspace_name=workspace_name,
            host_name=host_name,
            alias=alias,
            shared_from_workspace=shared_from,
        )
        .on_conflict_do_nothing(constraint="uq_wth_login_ws_host")
    )
    await conn.execute(stmt)


async def count_owned_test_hosts(
    login: str, workspace_name: str, conn: AsyncConnection
) -> int:
    """Nombre de VM de test POSSÉDÉES par un workspace (hors partagées).

    Sert à la numérotation `<N>` à la création : une VM partagée-vers ce
    workspace ne doit pas décaler le compteur des VM qu'il crée lui-même.
    """
    rows = (
        await conn.execute(
            select(_t.c.id).where(
                (_t.c.login == login)
                & (_t.c.workspace_name == workspace_name)
                & (_t.c.shared_from_workspace.is_(None))
            )
        )
    ).all()
    return len(rows)


async def is_owned_test_host(
    login: str, workspace_name: str, host_name: str, conn: AsyncConnection
) -> bool:
    """True si (login, workspace) est le PROPRIÉTAIRE du host (pas un partage).

    Garde des opérations de cycle de vie (suppression, resolve-ip) : un workspace
    à qui la VM est seulement partagée ne doit pas pouvoir la détruire/muter.
    """
    row = (
        await conn.execute(
            select(_t.c.id).where(
                (_t.c.login == login)
                & (_t.c.workspace_name == workspace_name)
                & (_t.c.host_name == host_name)
                & (_t.c.shared_from_workspace.is_(None))
            )
        )
    ).first()
    return row is not None


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


async def list_test_hosts_with_share(
    login: str, workspace_name: str, conn: AsyncConnection
) -> list[tuple[str, str, str | None]]:
    """(host_name, alias, shared_from) des hosts d'un workspace (possédés + partagés).

    `shared_from` non-NULL marque une VM partagée-vers ce workspace (bloc en
    lecture seule côté carte). Triés par numéro d'alias.
    """
    rows = (
        await conn.execute(
            select(_t.c.host_name, _t.c.alias, _t.c.shared_from_workspace).where(
                (_t.c.login == login) & (_t.c.workspace_name == workspace_name)
            )
        )
    ).all()

    def _alias_num(alias: str | None) -> int:
        m = _ALIAS_RE.match(alias or "")
        return int(m.group(1)) if m else 1_000_000

    triples = [(r[0], r[1] or "", r[2]) for r in rows]
    return sorted(triples, key=lambda p: _alias_num(p[1]))


# ─── Partage d'une VM de test vers d'autres workspaces ───────────────────────


async def share_test_host(
    login: str,
    owner_workspace: str,
    host_name: str,
    target_workspace: str,
    alias: str,
    conn: AsyncConnection,
) -> None:
    """Partage la VM `host_name` (possédée par `owner_workspace`) vers
    `target_workspace` avec son propre `alias`. Idempotent."""
    await assign_test_host(
        login, target_workspace, host_name, alias, conn, shared_from=owner_workspace
    )


async def unshare_test_host(
    login: str, host_name: str, target_workspace: str, conn: AsyncConnection
) -> tuple[str, int | None] | None:
    """Retire le partage de `host_name` vers `target_workspace`.

    Retourne (alias, message_id) de la ligne supprimée pour permettre le nettoyage
    (bloc ssh config du container, message contextuel), ou None si aucun partage.
    Ne supprime QUE des lignes de partage (shared_from non-NULL) — jamais le
    propriétaire.
    """
    row = (
        await conn.execute(
            select(_t.c.alias, _t.c.message_id).where(
                (_t.c.login == login)
                & (_t.c.workspace_name == target_workspace)
                & (_t.c.host_name == host_name)
                & (_t.c.shared_from_workspace.is_not(None))
            )
        )
    ).first()
    if row is None:
        return None
    await conn.execute(
        delete(_t).where(
            (_t.c.login == login)
            & (_t.c.workspace_name == target_workspace)
            & (_t.c.host_name == host_name)
            & (_t.c.shared_from_workspace.is_not(None))
        )
    )
    return (row[0] or "", row[1])


async def list_shared_targets(
    login: str, host_name: str, conn: AsyncConnection
) -> list[tuple[str, str, int | None]]:
    """(target_workspace, alias, message_id) des workspaces à qui `host_name` est partagé."""
    rows = (
        await conn.execute(
            select(_t.c.workspace_name, _t.c.alias, _t.c.message_id).where(
                (_t.c.login == login)
                & (_t.c.host_name == host_name)
                & (_t.c.shared_from_workspace.is_not(None))
            )
        )
    ).all()
    return [(r[0], r[1] or "", r[2]) for r in rows]


async def set_shared_message_id(
    login: str,
    host_name: str,
    target_workspace: str,
    message_id: int | None,
    conn: AsyncConnection,
) -> None:
    """Enregistre le message contextuel d'un partage (ligne de partage uniquement)."""
    await conn.execute(
        update(_t)
        .where(
            (_t.c.login == login)
            & (_t.c.workspace_name == target_workspace)
            & (_t.c.host_name == host_name)
            & (_t.c.shared_from_workspace.is_not(None))
        )
        .values(message_id=message_id)
    )


async def list_all_test_hosts(
    conn: AsyncConnection,
) -> list[tuple[str, str, str, str]]:
    """(login, workspace_name, host_name, alias) de toutes les associations de test.

    Vue admin de l'agrégation des sessions : toutes les VM de test, tous users.
    """
    rows = (
        await conn.execute(select(_t.c.login, _t.c.workspace_name, _t.c.host_name, _t.c.alias))
    ).all()
    return [(r[0], r[1], r[2], r[3] or "") for r in rows]


async def list_test_hosts_for_login(
    login: str, conn: AsyncConnection
) -> list[tuple[str, str, str, str]]:
    """(login, workspace_name, host_name, alias) des VM de test d'un login."""
    rows = (
        await conn.execute(
            select(_t.c.login, _t.c.workspace_name, _t.c.host_name, _t.c.alias).where(
                _t.c.login == login
            )
        )
    ).all()
    return [(r[0], r[1], r[2], r[3] or "") for r in rows]


async def workspace_for_host(
    host_name: str, conn: AsyncConnection
) -> tuple[str, str] | None:
    """(login, workspace_name) propriétaire d'un host de test, ou None."""
    row = (
        await conn.execute(
            select(_t.c.login, _t.c.workspace_name).where(
                (_t.c.host_name == host_name) & (_t.c.shared_from_workspace.is_(None))
            )
        )
    ).mappings().first()
    return (row["login"], row["workspace_name"]) if row else None


async def host_full_info(
    host_name: str, conn: AsyncConnection
) -> tuple[str, str, str] | None:
    """(login, workspace_name, alias) pour un host de test (propriétaire), ou None."""
    row = (
        await conn.execute(
            select(_t.c.login, _t.c.workspace_name, _t.c.alias).where(
                (_t.c.host_name == host_name) & (_t.c.shared_from_workspace.is_(None))
            )
        )
    ).mappings().first()
    return (row["login"], row["workspace_name"], row["alias"] or "") if row else None


async def get_test_host_message_id(
    host_name: str, conn: AsyncConnection
) -> int | None:
    """Retourne le message_id du host de test (ligne propriétaire), ou None."""
    return (
        await conn.execute(
            select(_t.c.message_id).where(
                (_t.c.host_name == host_name) & (_t.c.shared_from_workspace.is_(None))
            )
        )
    ).scalar_one_or_none()


async def set_test_host_message_id(
    host_name: str, message_id: int | None, conn: AsyncConnection
) -> None:
    """Enregistre le message_id du host de test (ligne propriétaire)."""
    await conn.execute(
        update(_t)
        .where((_t.c.host_name == host_name) & (_t.c.shared_from_workspace.is_(None)))
        .values(message_id=message_id)
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
