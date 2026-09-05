"""Persistance des abonnements.

Ce module écrit et lit ; il ne décide pas. Les règles — transitions d'état,
échéance du forfait, éligibilité — vivent dans `billing.subscriptions` et
`billing.eligibilite`, qui travaillent sur ce que ce module leur donne. Les
dupliquer en SQL ferait exister deux vérités qui divergeraient au premier
changement.

`currency` et `amount_minor` sont un INSTANTANÉ du prix au moment de la
souscription, jamais une lecture du catalogue : celui-ci évolue, un abonné garde
le prix auquel il a souscrit, et une facture ancienne reste reproductible.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.subscriptions import Subscription
from .tables import subscriptions


def _row_to_subscription(row: dict[str, Any]) -> Subscription:
    return Subscription.model_validate(
        {
            "id": row["id"],
            "login": row["login"],
            "offer_slug": row["offer_slug"],
            "provider_slug": row["provider_slug"],
            "state": row["state"],
            "country_code": row["country_code"],
            "currency": row["currency"],
            "amount_minor": row["amount_minor"],
            "provider_subscription_id": row["provider_subscription_id"],
            "payment_attempts": row["payment_attempts"],
            "next_retry_at": row["next_retry_at"],
            "trial_end": row["trial_end"],
            "current_period_end": row["current_period_end"],
            "ends_at": row["ends_at"],
            "state_changed_at": row["state_changed_at"],
        }
    )


async def creer(abonnement: Subscription, conn: AsyncConnection) -> None:
    """Insère un abonnement neuf.

    Insertion sèche, sans `ON CONFLICT` : l'identifiant est tiré par l'appelant
    et une collision signalerait un défaut qu'on ne doit pas absorber en
    silence. L'idempotence du parcours se joue en amont, sur l'éligibilité et
    sur le garde-fou de double soumission — pas ici.
    """
    await conn.execute(
        subscriptions.insert().values(
            id=abonnement.id,
            login=abonnement.login,
            offer_slug=abonnement.offer_slug,
            provider_slug=abonnement.provider_slug,
            state=abonnement.state,
            country_code=abonnement.country_code,
            currency=abonnement.currency,
            amount_minor=abonnement.amount_minor,
            provider_subscription_id=abonnement.provider_subscription_id,
            payment_attempts=abonnement.payment_attempts,
            next_retry_at=abonnement.next_retry_at,
            trial_end=abonnement.trial_end,
            current_period_end=abonnement.current_period_end,
            ends_at=abonnement.ends_at,
        )
    )


async def enregistrer_etat(abonnement: Subscription, conn: AsyncConnection) -> None:
    """Réécrit les champs qu'une transition fait bouger, et eux seuls.

    Pas de remplacement complet de la ligne : `country_code`, `currency` et
    `amount_minor` sont un instantané figé à la souscription. Les réécrire
    depuis un objet reconstitué ouvrirait la porte à ce qu'un événement de
    cycle réécrive le prix d'une facture déjà émise.
    """
    await conn.execute(
        subscriptions.update()
        .where(subscriptions.c.id == abonnement.id)
        .values(
            state=abonnement.state,
            state_changed_at=abonnement.state_changed_at,
            payment_attempts=abonnement.payment_attempts,
            next_retry_at=abonnement.next_retry_at,
            trial_end=abonnement.trial_end,
            current_period_end=abonnement.current_period_end,
            provider_subscription_id=abonnement.provider_subscription_id,
        )
    )


async def par_identifiant_fournisseur(
    provider_subscription_id: str, conn: AsyncConnection
) -> Subscription | None:
    """Retrouve un abonnement depuis l'identifiant du FOURNISSEUR.

    Chemin de repli quand l'événement ne porte pas notre identifiant en
    métadonnée. Vide exclu : une chaîne vide est la valeur par défaut de la
    colonne, elle apparierait n'importe quel abonnement jamais poussé au
    fournisseur.
    """
    if not provider_subscription_id:
        return None
    row = (
        (
            await conn.execute(
                select(subscriptions).where(
                    subscriptions.c.provider_subscription_id == provider_subscription_id
                )
            )
        )
        .mappings()
        .first()
    )
    return None if row is None else _row_to_subscription(dict(row))


async def get(subscription_id: str, conn: AsyncConnection) -> Subscription | None:
    row = (
        (await conn.execute(select(subscriptions).where(subscriptions.c.id == subscription_id)))
        .mappings()
        .first()
    )
    return None if row is None else _row_to_subscription(dict(row))


async def list_de(login: str, conn: AsyncConnection) -> list[Subscription]:
    """Abonnements d'un compte, du plus récent au plus ancien.

    Tous états confondus, résiliés compris : un abonné doit pouvoir relire son
    historique, et un résilié peut reprendre.
    """
    stmt = (
        select(subscriptions)
        .where(subscriptions.c.login == login)
        .order_by(subscriptions.c.created_at.desc(), subscriptions.c.id)
    )
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row_to_subscription(dict(r)) for r in rows]


async def offres_deja_souscrites(login: str, conn: AsyncConnection) -> set[str]:
    """Slugs des offres que ce compte a déjà souscrites, quel que soit l'état.

    Sert la règle `une_par_compte`. **Un abonnement résilié compte** : sans quoi
    il suffirait de résilier pour reprendre une offre de bienvenue, ce qui
    viderait la règle de son sens.
    """
    stmt = select(subscriptions.c.offer_slug).where(subscriptions.c.login == login)
    return set((await conn.execute(stmt)).scalars().all())
