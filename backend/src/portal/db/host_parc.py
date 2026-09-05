"""L'écran d'exploitation du parc : qu'est-ce que c'est, à qui, ça tient ?

Une seule requête sert la page : `hosts` joint à la propriété
(`host_ownership`), à la dernière sonde (`host_disk`) et au décompte agrégé des
workspaces — jamais une requête par ligne. Filtres, tri et pagination sont
CÔTÉ SERVEUR : trier la page courante au lieu de l'ensemble donnerait un
classement faux dès la seconde page.

Deux règles qui ne se voient pas dans une capture d'écran :

- **les inconnus vont en fin de tri, dans les deux sens.** Un host jamais sondé
  n'a pas de ligne `host_disk` — l'absence se lit « inconnu », jamais « 0 % ».
  Un tri naïf le placerait en tête du classement « disque le plus libre »,
  c'est-à-dire recommanderait d'y poser des workspaces ;
- **l'ordre est stable** : à valeur égale, le nom départage. Sans clé
  secondaire, une machine peut apparaître sur deux pages ou sur aucune.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import host_disk, host_ownership, hosts, workspace_status

TriParc = Literal["nom", "workspaces", "disque", "memoire"]

#: Valeur du filtre propriétaire qui sélectionne le POOL. « Mutualisé » nomme ce
#: que la machine EST, pas ce qui lui manque — décision de l'architecte
#: (31/08/2026) : le pool a sa place dans le filtre, au même titre qu'un compte.
FILTRE_MUTUALISE = "__mutualise__"


class LigneParc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    usage: str
    accepts_mutualise: bool
    #: `None` sur une mutualisée — deux natures, deux rendus : ce vide ne doit
    #: jamais se lire « propriétaire inconnu ».
    owner_login: str | None
    workspaces: int
    #: `None` = jamais sondé (pas de ligne host_disk) — PAS 0 %.
    disk_used_pct: int | None
    mem_used_bytes: int | None
    mem_total_bytes: int | None
    hypervisor: str
    capacity_workspaces: int | None


class PageParc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    page: int
    page_size: int
    #: Les comptes propriétaires connus, pour alimenter le filtre.
    proprietaires: list[str]
    hosts: list[LigneParc]


def _appliquer_filtres(
    stmt: Select[Any],
    *,
    q: str,
    owner: str,
    hors_usages: list[str],
) -> Select[Any]:
    if q.strip():
        stmt = stmt.where(hosts.c.name.ilike(f"%{q.strip()}%"))
    if owner == FILTRE_MUTUALISE:
        stmt = stmt.where(hosts.c.accepts_mutualise.is_(True))
    elif owner:
        stmt = stmt.where(host_ownership.c.owner_login == owner)
    if hors_usages:
        stmt = stmt.where(hosts.c.usage.notin_(hors_usages))
    return stmt


async def lister_parc(
    conn: AsyncConnection,
    *,
    q: str = "",
    owner: str = "",
    tri: TriParc = "nom",
    descendant: bool = False,
    page: int = 1,
    page_size: int = 25,
    hors_usages: list[str] | None = None,
) -> PageParc:
    comptes = (
        select(
            workspace_status.c.host_name.label("host_name"),
            func.count().label("workspaces"),
        )
        .group_by(workspace_status.c.host_name)
        .subquery()
    )
    base = (
        hosts.outerjoin(host_ownership, host_ownership.c.host_name == hosts.c.name)
        .outerjoin(host_disk, host_disk.c.name == hosts.c.name)
        .outerjoin(comptes, comptes.c.host_name == hosts.c.name)
    )

    colonnes = select(
        hosts.c.name,
        hosts.c.usage,
        hosts.c.accepts_mutualise,
        hosts.c.hypervisor,
        hosts.c.capacity_workspaces,
        host_ownership.c.owner_login,
        func.coalesce(comptes.c.workspaces, 0).label("workspaces"),
        host_disk.c.used_pct.label("disk_used_pct"),
        host_disk.c.mem_used_bytes,
        host_disk.c.mem_total_bytes,
    ).select_from(base)
    colonnes = _appliquer_filtres(colonnes, q=q, owner=owner, hors_usages=hors_usages or [])

    # Le décompte de workspaces est CONNU même sans ligne (0 réel) ; le disque
    # et la mémoire viennent de la sonde — absents = inconnus, en fin de tri
    # dans les DEUX sens.
    cles = {
        "nom": hosts.c.name,
        "workspaces": func.coalesce(comptes.c.workspaces, 0),
        "disque": host_disk.c.used_pct,
        "memoire": host_disk.c.mem_used_bytes,
    }
    cle = cles[tri]
    principale = cle.desc() if descendant else cle.asc()
    if tri in {"disque", "memoire"}:
        principale = principale.nulls_last()
    colonnes = colonnes.order_by(principale, hosts.c.name.asc())

    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    rows = (
        (await conn.execute(colonnes.limit(page_size).offset((page - 1) * page_size)))
        .mappings()
        .all()
    )

    total_stmt = _appliquer_filtres(
        select(func.count()).select_from(base), q=q, owner=owner, hors_usages=hors_usages or []
    )
    total = (await conn.execute(total_stmt)).scalar_one()

    proprietaires = (
        (
            await conn.execute(
                select(host_ownership.c.owner_login)
                .distinct()
                .order_by(host_ownership.c.owner_login)
            )
        )
        .scalars()
        .all()
    )
    return PageParc(
        total=int(total),
        page=page,
        page_size=page_size,
        proprietaires=list(proprietaires),
        hosts=[LigneParc.model_validate(dict(r)) for r in rows],
    )
