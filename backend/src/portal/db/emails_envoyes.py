"""Journal des emails du cycle d'abonnement : réservé, envoyé, ou en échec.

Deux rôles, un seul registre :

- **l'idempotence** : la contrainte `(subscription_id, kind, dedup_key)`
  tranche à l'écriture, comme `provisioning_runs` — un webhook rejoué ou un
  double passage du balayeur n'envoie pas deux fois ;
- **la preuve** : le payload est FIGÉ dans la ligne. Les dates limites y sont
  calculées depuis la politique de rétention au moment de l'envoi — si la
  politique change ensuite, on peut toujours prouver ce qui a été annoncé.

La réservation s'écrit AVANT l'envoi : un envoi qui échoue laisse une ligne
`echec` visible et journalisée — préférable à l'inverse (un mail de
destruction envoyé deux fois).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import emails_envoyes


async def reserver(
    conn: AsyncConnection,
    *,
    subscription_id: str,
    kind: str,
    dedup_key: str,
    destinataire: str,
    culture: str,
    template: str,
    data: dict[str, Any],
) -> int | None:
    """Réserve l'envoi. `None` si cet épisode a déjà le sien."""
    stmt = (
        pg_insert(emails_envoyes)
        .values(
            subscription_id=subscription_id,
            kind=kind,
            dedup_key=dedup_key,
            destinataire=destinataire,
            culture=culture,
            template=template,
            data=data,
            statut="reserve",
        )
        .on_conflict_do_nothing(constraint="uq_email_envoye_episode")
        .returning(emails_envoyes.c.id)
    )
    return (await conn.execute(stmt)).scalar_one_or_none()


async def marquer(
    email_id: int,
    statut: str,
    conn: AsyncConnection,
    *,
    erreur: str = "",
) -> None:
    await conn.execute(
        update(emails_envoyes)
        .where(emails_envoyes.c.id == email_id)
        .values(statut=statut, erreur=erreur, updated_at=func.now())
    )


async def lister_echecs(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Les envois en échec, le plus ancien d'abord — l'écart à réparer."""
    stmt = (
        select(emails_envoyes)
        .where(emails_envoyes.c.statut == "echec")
        .order_by(emails_envoyes.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]
