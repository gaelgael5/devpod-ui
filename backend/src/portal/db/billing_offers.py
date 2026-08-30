"""Accès en base aux taux de taxe et aux offres d'abonnement.

Deux natures d'écriture cohabitent ici, et il ne faut pas les confondre :

- un taux de taxe s'AJOUTE et se CLÔT, jamais ne s'écrase — une facture émise
  l'an dernier doit rester reproductible avec le taux de l'époque ;
- une offre se remplace librement tant qu'elle n'a pas été souscrite ; l'abonné,
  lui, garde un instantané du prix dans sa propre ligne d'abonnement.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.models import Offer, OfferPrice, TaxRate
from .tables import offer_prices, offers, subscriptions, tax_rates

# ─── Taux de taxe ────────────────────────────────────────────────────────────


async def list_tax_rates(
    conn: AsyncConnection, *, country_code: str | None = None
) -> list[TaxRate]:
    """Historique complet, du plus ancien au plus récent.

    Complet et non « en vigueur » : c'est l'historique qui rend une facture
    ancienne reproductible, et l'admin doit le voir pour ce qu'il est.
    """
    stmt = select(tax_rates)
    if country_code is not None:
        stmt = stmt.where(tax_rates.c.country_code == country_code)
    stmt = stmt.order_by(tax_rates.c.country_code, tax_rates.c.region, tax_rates.c.valid_from)
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row_to_tax_rate(dict(r)) for r in rows]


def _row_to_tax_rate(row: dict[str, Any]) -> TaxRate:
    return TaxRate.model_validate(
        {
            "id": row["id"],
            "country_code": row["country_code"],
            "region": row["region"],
            "rate": row["rate"],
            "label": row["label"],
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
        }
    )


async def get_tax_rate(rate_id: int, conn: AsyncConnection) -> TaxRate | None:
    row = (
        (await conn.execute(select(tax_rates).where(tax_rates.c.id == rate_id))).mappings().first()
    )
    return _row_to_tax_rate(dict(row)) if row else None


async def add_tax_rate(taux: TaxRate, conn: AsyncConnection) -> TaxRate:
    """Insère un taux et renvoie sa version persistée, identité comprise.

    L'`id` du modèle entrant est ignoré : c'est la base qui numérote.
    """
    vals = taux.model_dump(exclude={"id"})
    nouvel_id = (
        await conn.execute(insert(tax_rates).values(**vals).returning(tax_rates.c.id))
    ).scalar_one()
    return taux.model_copy(update={"id": nouvel_id})


async def close_tax_rate(rate_id: int, valid_to: date, conn: AsyncConnection) -> bool:
    """Pose la fin de validité. C'est la seule mutation permise sur un taux."""
    res = await conn.execute(
        update(tax_rates).where(tax_rates.c.id == rate_id).values(valid_to=valid_to)
    )
    return bool(res.rowcount)


async def delete_tax_rate(rate_id: int, conn: AsyncConnection) -> bool:
    """Efface un taux. Réservé par la route aux taux pas encore en vigueur —
    ceux-là n'ont rien pu facturer."""
    res = await conn.execute(delete(tax_rates).where(tax_rates.c.id == rate_id))
    return bool(res.rowcount)


# ─── Offres ──────────────────────────────────────────────────────────────────


def _row_to_offer(row: dict[str, Any], prix: list[OfferPrice]) -> Offer:
    return Offer.model_validate(
        {
            "slug": row["slug"],
            "label": row["label"] or "",
            "titles": row["titles"] or {},
            "descriptions": row["descriptions"] or {},
            "hosting_type": row["hosting_type"],
            "max_workspaces": row["max_workspaces"],
            "max_hosts_dedies": row["max_hosts_dedies"],
            "variables": row["variables"] or {},
            "provider_slug": row["provider_slug"],
            "published": row["published"],
            "prices_include_tax": row["prices_include_tax"],
            "auto_currencies": row["auto_currencies"],
            "currency_markup": row["currency_markup"],
            "is_free": row["is_free"],
            "duration_days": row["duration_days"],
            "prices": prix,
        }
    )


async def _prix_par_offre(slugs: list[str], conn: AsyncConnection) -> dict[str, list[OfferPrice]]:
    """Prix des offres demandées, groupés par slug — une requête, pas N."""
    if not slugs:
        return {}
    stmt = (
        select(offer_prices)
        .where(offer_prices.c.offer_slug.in_(slugs))
        .order_by(offer_prices.c.currency)
    )
    groupes: dict[str, list[OfferPrice]] = defaultdict(list)
    for row in (await conn.execute(stmt)).mappings().all():
        groupes[row["offer_slug"]].append(
            OfferPrice.model_validate(
                {
                    "currency": row["currency"],
                    "amount_minor": row["amount_minor"],
                    "provider_price_id": row["provider_price_id"],
                }
            )
        )
    return dict(groupes)


async def list_offers(conn: AsyncConnection, *, published_only: bool = False) -> list[Offer]:
    stmt = select(offers)
    if published_only:
        stmt = stmt.where(offers.c.published.is_(True))
    rows = [dict(r) for r in (await conn.execute(stmt.order_by(offers.c.slug))).mappings().all()]
    prix = await _prix_par_offre([r["slug"] for r in rows], conn)
    return [_row_to_offer(r, prix.get(r["slug"], [])) for r in rows]


async def get_offer(slug: str, conn: AsyncConnection) -> Offer | None:
    row = (await conn.execute(select(offers).where(offers.c.slug == slug))).mappings().first()
    if row is None:
        return None
    prix = await _prix_par_offre([slug], conn)
    return _row_to_offer(dict(row), prix.get(slug, []))


async def upsert_offer(offre: Offer, conn: AsyncConnection) -> None:
    """Crée ou remplace, prix compris.

    Les prix sont effacés puis réinsérés : le corps reçu décrit l'état voulu du
    tarif, pas un delta. Un prix retiré du corps doit disparaître, sans quoi une
    devise abandonnée resterait vendable.
    """
    vals: dict[str, Any] = {
        "slug": offre.slug,
        "label": offre.label,
        "titles": dict(offre.titles),
        "descriptions": dict(offre.descriptions),
        "hosting_type": offre.hosting_type,
        "max_workspaces": offre.max_workspaces,
        "max_hosts_dedies": offre.max_hosts_dedies,
        "variables": dict(offre.variables),
        "provider_slug": offre.provider_slug,
        "published": offre.published,
        "prices_include_tax": offre.prices_include_tax,
        "auto_currencies": offre.auto_currencies,
        "currency_markup": offre.currency_markup,
        "is_free": offre.is_free,
        "duration_days": offre.duration_days,
    }
    existe = (
        await conn.execute(select(offers.c.slug).where(offers.c.slug == offre.slug))
    ).scalar_one_or_none()
    if existe is None:
        await conn.execute(insert(offers).values(**vals))
    else:
        vals.pop("slug")
        vals["updated_at"] = func.now()
        await conn.execute(update(offers).where(offers.c.slug == offre.slug).values(**vals))

    await conn.execute(delete(offer_prices).where(offer_prices.c.offer_slug == offre.slug))
    if offre.prices:
        await conn.execute(
            insert(offer_prices),
            [{"offer_slug": offre.slug, **p.model_dump()} for p in offre.prices],
        )


async def delete_offer(slug: str, conn: AsyncConnection) -> bool:
    res = await conn.execute(delete(offers).where(offers.c.slug == slug))
    return bool(res.rowcount)


async def offer_reference(slug: str, conn: AsyncConnection) -> bool:
    """Un abonnement porte-t-il cette offre ?

    Supprimer une offre souscrite couperait le lien entre un abonné et ce pour
    quoi il paie. Une offre qu'on ne veut plus vendre se DÉPUBLIE.
    """
    stmt = select(func.count()).select_from(subscriptions).where(subscriptions.c.offer_slug == slug)
    return bool((await conn.execute(stmt)).scalar_one())
