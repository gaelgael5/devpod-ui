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

RunState = Literal["decide", "en_cours", "fait", "echec"]


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
            motif=decision.motif,
            state="decide",
        )
        .on_conflict_do_nothing(constraint="uq_provisioning_run_event")
        .returning(provisioning_runs.c.id)
    )
    return (await conn.execute(stmt)).scalar_one_or_none()


async def marquer(run_id: int, state: RunState, conn: AsyncConnection, *, erreur: str = "") -> None:
    """Fait avancer une tentative.

    `erreur` est réécrite à chaque passage, y compris avec une chaîne vide :
    une reprise qui réussit après un échec ne doit pas laisser traîner le
    message précédent, sinon l'écran d'exploitation ment.
    """
    await conn.execute(
        update(provisioning_runs)
        .where(provisioning_runs.c.id == run_id)
        .values(state=state, erreur=erreur, updated_at=func.now())
    )


async def lire(run_id: int, conn: AsyncConnection) -> dict[str, Any] | None:
    row = (
        (await conn.execute(select(provisioning_runs).where(provisioning_runs.c.id == run_id)))
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def lister_echecs(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Tentatives en échec, la plus ancienne d'abord.

    L'ancienneté d'abord : un provisioning en échec depuis trois jours est plus
    urgent que celui d'il y a dix minutes, qui se rejouera peut-être tout seul.
    """
    stmt = (
        select(provisioning_runs)
        .where(provisioning_runs.c.state == "echec")
        .order_by(provisioning_runs.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]
