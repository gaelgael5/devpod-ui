"""Accès en base au catalogue de facturation : pays, devises, canaux de paiement.

Ce module ne décide rien — il lit et écrit. Les règles (une seule devise par
défaut, un provider référencé ne se supprime pas) sont dans les routes, parce
qu'elles doivent produire un message d'erreur destiné à un humain.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.models import Country, CountryProvider, Currency, PaymentProvider
from .tables import (
    countries,
    country_providers,
    currencies,
    offers,
    payment_providers,
    subscriptions,
)

# ─── Pays ────────────────────────────────────────────────────────────────────


def _row_to_country(row: dict[str, Any]) -> Country:
    """Projette la ligne sur les seuls champs du modèle.

    La table porte `created_at` / `updated_at`, que `Country` ne déclare pas et
    refuse (`extra="forbid"`) : valider la ligne entière lèverait une
    ValidationError à la lecture.
    """
    return Country(code=row["code"], label=row["label"], enabled=row["enabled"])


async def list_countries(conn: AsyncConnection) -> list[Country]:
    """Pays triés par libellé — c'est ce que l'œil lit."""
    rows = (await conn.execute(select(countries).order_by(countries.c.label))).mappings().all()
    return [_row_to_country(dict(r)) for r in rows]


async def get_country(code: str, conn: AsyncConnection) -> Country | None:
    stmt = select(countries).where(countries.c.code == code)
    row = (await conn.execute(stmt)).mappings().first()
    return _row_to_country(dict(row)) if row else None


async def upsert_country(pays: Country, conn: AsyncConnection) -> None:
    """Crée ou remplace. Le code ISO est l'identité : il ne se renomme pas."""
    existe = (
        await conn.execute(select(countries.c.code).where(countries.c.code == pays.code))
    ).scalar_one_or_none()
    if existe is None:
        await conn.execute(insert(countries).values(**pays.model_dump()))
        return
    await conn.execute(
        update(countries)
        .where(countries.c.code == pays.code)
        .values(label=pays.label, enabled=pays.enabled, updated_at=func.now())
    )


async def delete_country(code: str, conn: AsyncConnection) -> bool:
    """`True` si un pays a bien été supprimé. Les rattachements de canaux
    suivent (`ON DELETE CASCADE`) : ils n'ont pas de sens sans leur pays. Les
    devises, elles, sont globales et ne bougent pas."""
    res = await conn.execute(delete(countries).where(countries.c.code == code))
    return bool(res.rowcount)


# ─── Devises acceptees par l'application ─────────────────────────────────────


async def list_currencies(conn: AsyncConnection) -> list[Currency]:
    """Toutes les devises declarees, actives ou non, triees par code."""
    stmt = select(currencies).order_by(currencies.c.code)
    rows = (await conn.execute(stmt)).mappings().all()
    return [
        Currency(code=r["code"], enabled=r["enabled"], is_default=r["is_default"]) for r in rows
    ]


async def set_currencies(devises: list[Currency], conn: AsyncConnection) -> None:
    """Remplace le jeu de devises de l'application.

    Effacer puis reinserer, et non rapprocher ligne a ligne : l'index partiel
    unique sur `is_default` refuserait un etat transitoire a deux defauts, que
    tout rapprochement incremental traverserait tot ou tard.
    """
    await conn.execute(delete(currencies))
    if devises:
        await conn.execute(
            insert(currencies),
            [
                {"code": d.code, "enabled": d.enabled, "is_default": d.is_default}
                for d in devises
            ],
        )


async def devises_actives(conn: AsyncConnection) -> list[str]:
    """Codes des devises activees.

    C'est le referentiel du garde-fou a la publication : une offre sans prix
    dans aucune de ces devises n'est proposable a personne.
    """
    stmt = (
        select(currencies.c.code).where(currencies.c.enabled.is_(True)).order_by(currencies.c.code)
    )
    return list((await conn.execute(stmt)).scalars().all())


# ─── Canaux de paiement ──────────────────────────────────────────────────────


def _row_to_provider(row: dict[str, Any]) -> PaymentProvider:
    return PaymentProvider.model_validate(
        {
            "slug": row["slug"],
            "kind": row["kind"],
            "label": row["label"],
            "tax_mode": row["tax_mode"],
            "enabled": row["enabled"],
            "config": row["config"] or {},
            "secret_slug": row["secret_slug"],
        }
    )


async def list_providers(conn: AsyncConnection) -> list[PaymentProvider]:
    stmt = select(payment_providers).order_by(payment_providers.c.label)
    rows = (await conn.execute(stmt)).mappings().all()
    return [_row_to_provider(dict(r)) for r in rows]


async def get_provider(slug: str, conn: AsyncConnection) -> PaymentProvider | None:
    stmt = select(payment_providers).where(payment_providers.c.slug == slug)
    row = (await conn.execute(stmt)).mappings().first()
    return _row_to_provider(dict(row)) if row else None


async def upsert_provider(provider: PaymentProvider, conn: AsyncConnection) -> None:
    """Crée ou remplace. Aucun secret n'entre ici : `secret_slug` est une
    référence vers la table des secrets, jamais la clé."""
    vals: dict[str, Any] = {
        "slug": provider.slug,
        "kind": provider.kind,
        "label": provider.label,
        "tax_mode": provider.tax_mode,
        "enabled": provider.enabled,
        "config": dict(provider.config),
        "secret_slug": provider.secret_slug,
    }
    existe = (
        await conn.execute(
            select(payment_providers.c.slug).where(payment_providers.c.slug == provider.slug)
        )
    ).scalar_one_or_none()
    if existe is None:
        await conn.execute(insert(payment_providers).values(**vals))
        return
    vals.pop("slug")
    vals["updated_at"] = func.now()
    await conn.execute(
        update(payment_providers).where(payment_providers.c.slug == provider.slug).values(**vals)
    )


async def delete_provider(slug: str, conn: AsyncConnection) -> bool:
    res = await conn.execute(delete(payment_providers).where(payment_providers.c.slug == slug))
    return bool(res.rowcount)


async def provider_reference(slug: str, conn: AsyncConnection) -> bool:
    """Une offre ou un abonnement s'appuie-t-il sur ce canal ?

    Le supprimer laisserait des abonnements sans moyen d'être prélevés — la base
    le refuserait (clé étrangère), mais avec un message que personne ne lit.
    """
    for table, colonne in (
        (offers, offers.c.provider_slug),
        (subscriptions, subscriptions.c.provider_slug),
    ):
        stmt = select(func.count()).select_from(table).where(colonne == slug)
        if (await conn.execute(stmt)).scalar_one():
            return True
    return False


# ─── Rattachement pays ↔ providers ───────────────────────────────────────────


async def list_country_providers(
    conn: AsyncConnection, *, country_code: str | None = None
) -> list[CountryProvider]:
    """Rattachements, par priorité croissante — c'est l'ordre d'essai."""
    stmt = select(country_providers)
    if country_code is not None:
        stmt = stmt.where(country_providers.c.country_code == country_code)
    stmt = stmt.order_by(country_providers.c.country_code, country_providers.c.priority)
    rows = (await conn.execute(stmt)).mappings().all()
    return [CountryProvider.model_validate(dict(r)) for r in rows]


async def set_country_providers(
    country_code: str, liens: list[CountryProvider], conn: AsyncConnection
) -> None:
    """Remplace le rattachement d'un pays."""
    await conn.execute(
        delete(country_providers).where(country_providers.c.country_code == country_code)
    )
    if liens:
        await conn.execute(insert(country_providers), [x.model_dump() for x in liens])
