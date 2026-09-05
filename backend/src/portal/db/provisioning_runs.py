"""Registre des provisionings : ce qui a été décidé, et ce qui en est advenu.

Un abonnement peut être payé sans que l'accès existe — création de VM en échec,
pool injoignable, script en erreur. Sans registre, cet écart est **invisible** :
le client paie, personne ne le sait, et on l'apprend par une réclamation. Ce
module rend l'échec listable.

Il écrit ce que `billing.provisioning` a décidé ; il ne décide rien lui-même.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.provisioning import Decision
from .tables import provisioning_runs

# `echec` : lignes antérieures à la migration 133 (issue inconnue, faute de
# taxonomie à l'époque) — le nouveau code ne l'écrit plus. La distinction qui
# compte n'est pas succès/échec, c'est ce qu'il reste derrière (ticket 6).
RunState = Literal[
    "decide",
    "en_cours",
    "fait",
    "echec",
    "echec_avant_creation",
    "echec_apres_creation",
    "indetermine",
]

_ETATS_ECHEC = ("echec", "echec_avant_creation", "echec_apres_creation", "indetermine")

#: Ce que chaque état autorise comme suite. `indetermine` n'est JAMAIS
#: rejouable automatiquement : un timeout en plein apply ne dit pas si la
#: ressource a été créée, et rejouer est la façon de facturer deux VM.
#: `echec_apres_creation` ne se rejoue pas à l'identique non plus : la machine
#: existe — on la reprend ou on la détruit d'abord.
_ETATS_REJOUABLES = ("echec", "echec_avant_creation")


def peut_rejouer(state: str) -> bool:
    return state in _ETATS_REJOUABLES


async def enregistrer(
    conn: AsyncConnection,
    *,
    subscription_id: str,
    provider_event_id: str,
    kind: str,
    owner_login: str,
    offer_slug: str,
    decision: Decision,
) -> int | None:
    """Trace un verdict. `None` si cet événement a déjà sa tentative.

    L'idempotence est portée par la contrainte d'unicité, pas par une lecture
    préalable : entre un `SELECT` et un `INSERT`, un second webhook a le temps
    de passer. `ON CONFLICT DO NOTHING` tranche à l'écriture, là où la course
    se joue vraiment.
    """
    stmt = (
        pg_insert(provisioning_runs)
        .values(
            subscription_id=subscription_id,
            provider_event_id=provider_event_id,
            kind=kind,
            owner_login=owner_login,
            offer_slug=offer_slug,
            action=decision.action,
            host_name=decision.host_name,
            host_profile=decision.cible.host_profile if decision.cible else None,
            machine_profile=decision.cible.machine_profile if decision.cible else None,
            hypervisor=decision.cible.hypervisor if decision.cible else None,
            noeud=(decision.cible.noeud if decision.cible else decision.noeud) or "",
            motif=decision.motif,
            state="decide",
        )
        .on_conflict_do_nothing(constraint="uq_provisioning_run_event")
        .returning(provisioning_runs.c.id)
    )
    return (await conn.execute(stmt)).scalar_one_or_none()


async def marquer(
    run_id: int,
    state: RunState,
    conn: AsyncConnection,
    *,
    erreur: str = "",
    provider: str | None = None,
    provider_ref: dict[str, Any] | None = None,
) -> None:
    """Fait avancer une tentative.

    `erreur` est réécrite à chaque passage, y compris avec une chaîne vide :
    une reprise qui réussit après un échec ne doit pas laisser traîner le
    message précédent, sinon l'écran d'exploitation ment.

    `provider`/`provider_ref` ne sont écrits que s'ils sont fournis : un état
    ultérieur (rejeu, destruction) ne doit pas effacer la référence de la
    machine laissée derrière — c'est elle qui évite l'orpheline.
    """
    values: dict[str, Any] = {"state": state, "erreur": erreur, "updated_at": func.now()}
    if provider is not None:
        values["provider"] = provider
    if provider_ref is not None:
        values["provider_ref"] = provider_ref
    await conn.execute(
        update(provisioning_runs).where(provisioning_runs.c.id == run_id).values(**values)
    )


async def requalifier_orphelins(conn: AsyncConnection) -> int:
    """`en_cours` sans runner = issue inconnue (coupure brutale en plein vol).

    Appelé au démarrage du portail : toute ligne restée `en_cours` est
    requalifiée `indetermine` — jamais rejouée automatiquement, toujours
    visible. C'est la garantie « aucun chemin ne laisse une machine existante
    sans ligne correspondante » : la ligne existait avant l'exécution, elle
    redevient actionnable ici.
    """
    result = await conn.execute(
        update(provisioning_runs)
        .where(provisioning_runs.c.state == "en_cours")
        .values(
            state="indetermine",
            erreur="runner interrompu en plein vol — issue inconnue, décision humaine requise",
            updated_at=func.now(),
        )
    )
    return int(result.rowcount or 0)


async def lire(run_id: int, conn: AsyncConnection) -> dict[str, Any] | None:
    row = (
        (await conn.execute(select(provisioning_runs).where(provisioning_runs.c.id == run_id)))
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def lister(
    conn: AsyncConnection, *, state: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    """Tentatives, les plus récentes d'abord — l'écran d'exploitation."""
    stmt = select(provisioning_runs).order_by(provisioning_runs.c.created_at.desc()).limit(limit)
    if state is not None:
        stmt = stmt.where(provisioning_runs.c.state == state)
    return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]


async def lister_echecs(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Tentatives en échec, la plus ancienne d'abord.

    L'ancienneté d'abord : un provisioning en échec depuis trois jours est plus
    urgent que celui d'il y a dix minutes, qui se rejouera peut-être tout seul.
    """
    stmt = (
        select(provisioning_runs)
        .where(provisioning_runs.c.state.in_(_ETATS_ECHEC))
        .order_by(provisioning_runs.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]
