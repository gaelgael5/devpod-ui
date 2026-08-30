"""Taux de taxe et offres d'abonnement.

Deux invariants gouvernent ce fichier :

- **un taux de taxe ne s'écrase pas.** Il s'ajoute, et se clôt en posant sa fin
  de validité. Une facture émise l'an dernier doit rester reproductible avec le
  taux de l'époque — écraser le taux ferait perdre à la facturation sa valeur
  probante au premier changement de TVA.
- **une offre publiée est une offre vendable.** Sans prix dans une devise
  activée, elle n'est proposable à personne : le refus est posé à la saisie,
  pas découvert dans une page de tarifs vide.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..billing.models import Offer, TaxRate
from ..billing.pricing import devises_manquantes, publiable
from ..db.billing_catalog import devises_actives, get_country, get_provider
from ..db.billing_offers import (
    add_tax_rate,
    close_tax_rate,
    delete_offer,
    delete_tax_rate,
    get_offer,
    get_tax_rate,
    list_offers,
    list_tax_rates,
    offer_reference,
    upsert_offer,
)
from ..db.engine import get_conn

router = APIRouter(tags=["billing-offers"])
log = structlog.get_logger(__name__)


class FinDeValidite(BaseModel):
    """Date de fin d'un taux. Bornée dans un modèle pour que `extra="forbid"`
    refuse un corps qui croirait pouvoir modifier le taux au passage."""

    model_config = ConfigDict(extra="forbid")

    valid_to: date


async def _pays_ou_404(code: str, conn: AsyncConnection) -> None:
    if await get_country(code, conn) is None:
        raise HTTPException(status_code=404, detail=f"Pays {code!r} introuvable")


async def _taux_ou_404(rate_id: int, conn: AsyncConnection) -> TaxRate:
    taux = await get_tax_rate(rate_id, conn)
    if taux is None:
        raise HTTPException(status_code=404, detail=f"Taux de taxe {rate_id} introuvable")
    return taux


# ─── Taux de taxe ────────────────────────────────────────────────────────────


def _se_chevauchent(a: TaxRate, b: TaxRate) -> bool:
    """Deux périodes se recouvrent-elles ? Bornes `[valid_from, valid_to[`,
    `valid_to` absent valant « sans fin »."""
    a_fin_ouverte = a.valid_to is None
    b_fin_ouverte = b.valid_to is None
    debut_a_avant_fin_b = b_fin_ouverte or a.valid_from < b.valid_to  # type: ignore[operator]
    debut_b_avant_fin_a = a_fin_ouverte or b.valid_from < a.valid_to  # type: ignore[operator]
    return bool(debut_a_avant_fin_b and debut_b_avant_fin_a)


@router.get("/billing/countries/{code}/tax-rates")
async def admin_list_tax_rates(
    code: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Historique complet, pas seulement le taux en vigueur — c'est lui qui
    rend une facture ancienne reproductible."""
    await _pays_ou_404(code, conn)
    return [t.model_dump() for t in await list_tax_rates(conn, country_code=code)]


@router.post("/billing/countries/{code}/tax-rates", status_code=201)
async def admin_add_tax_rate(
    code: str,
    body: TaxRate,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Ajoute un taux.

    Deux taux de même portée en vigueur le même jour rendraient le calcul
    ambigu : le chevauchement est refusé. Un taux RÉGIONAL peut en revanche
    recouvrir le taux national du même pays — le plus spécifique gagne, c'est
    la règle et non une ambiguïté.
    """
    if body.country_code != code:
        raise HTTPException(
            status_code=422,
            detail=(
                f"country_code du corps ({body.country_code!r}) différent "
                f"de celui de l'URL ({code!r})"
            ),
        )
    await _pays_ou_404(code, conn)
    for existant in await list_tax_rates(conn, country_code=code):
        if existant.region == body.region and _se_chevauchent(existant, body):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Un taux couvre déjà cette période pour {code!r}"
                    f"{f' / {body.region}' if body.region else ''} : "
                    f"{existant.label!r} depuis le {existant.valid_from} — "
                    "le clore avant d'en ouvrir un autre"
                ),
            )
    pose = await add_tax_rate(body, conn)
    log.info("billing_tax_rate_added", code=code, rate_id=pose.id, actor=user.login)
    return pose.model_dump()


@router.post("/billing/tax-rates/{rate_id}/close")
async def admin_close_tax_rate(
    rate_id: int,
    body: FinDeValidite,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Pose la fin de validité d'un taux. Seule mutation permise sur un taux :
    tout le reste passe par un nouveau taux."""
    taux = await _taux_ou_404(rate_id, conn)
    if body.valid_to <= taux.valid_from:
        raise HTTPException(
            status_code=422,
            detail=(
                f"fin de validité ({body.valid_to}) antérieure ou égale "
                f"au début ({taux.valid_from})"
            ),
        )
    await close_tax_rate(rate_id, body.valid_to, conn)
    log.info(
        "billing_tax_rate_closed", rate_id=rate_id, valid_to=str(body.valid_to), actor=user.login
    )
    return taux.model_copy(update={"valid_to": body.valid_to}).model_dump()


@router.delete("/billing/tax-rates/{rate_id}", status_code=204)
async def admin_delete_tax_rate(
    rate_id: int,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    """Efface un taux PAS ENCORE entré en vigueur — celui-là n'a rien pu
    facturer, c'est une saisie et elle se corrige. Un taux déjà en vigueur se
    clôt : il a pu servir à une facture."""
    taux = await _taux_ou_404(rate_id, conn)
    if taux.valid_from <= date.today():
        raise HTTPException(
            status_code=409,
            detail=(
                f"Le taux {rate_id} est en vigueur depuis le {taux.valid_from} et a pu "
                "servir à une facture — le clore plutôt que le supprimer"
            ),
        )
    await delete_tax_rate(rate_id, conn)
    log.info("billing_tax_rate_deleted", rate_id=rate_id, actor=user.login)


# ─── Offres ──────────────────────────────────────────────────────────────────


@router.get("/billing/offers")
async def admin_list_offers(
    published_only: bool = False,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return [o.model_dump() for o in await list_offers(conn, published_only=published_only)]


@router.get("/billing/offers/{slug}")
async def admin_get_offer(
    slug: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    offre = await get_offer(slug, conn)
    if offre is None:
        raise HTTPException(status_code=404, detail=f"Offre {slug!r} introuvable")
    return offre.model_dump()


@router.put("/billing/offers/{slug}")
async def admin_save_offer(
    slug: str,
    body: Offer,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Crée ou remplace, prix compris.

    La réponse porte `devises_manquantes` : les devises activées pour lesquelles
    l'offre n'a pas de prix. Ce n'est pas un refus — l'offre reste vendable
    ailleurs — mais l'absence doit se voir à la saisie.
    """
    if body.slug != slug:
        raise HTTPException(
            status_code=422,
            detail=f"slug du corps ({body.slug!r}) différent de celui de l'URL ({slug!r})",
        )
    if body.provider_slug is not None and await get_provider(body.provider_slug, conn) is None:
        raise HTTPException(
            status_code=422, detail=f"Canal de paiement {body.provider_slug!r} introuvable"
        )

    actives = await devises_actives(conn)
    if body.published:
        # Deux refus distincts : le message doit dire lequel, sinon
        # l'administrateur cherche un prix alors qu'il manque une durée.
        if body.duration_days is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Offre non publiable : aucune durée de forfait — "
                    "un essai sans fin est un produit offert, et un abonnement "
                    "sans terme ne se facture pas"
                ),
            )
        if not publiable(body, actives):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Offre non publiable : aucun prix dans une devise activée "
                    f"({', '.join(actives) or 'aucune devise activée'}) — "
                    "elle ne serait proposable à personne"
                ),
            )

    await upsert_offer(body, conn)
    manquantes = devises_manquantes(body, actives)
    log.info(
        "billing_offer_saved",
        slug=slug,
        published=body.published,
        devises_manquantes=manquantes,
        actor=user.login,
    )
    return {**body.model_dump(), "devises_manquantes": manquantes}


@router.delete("/billing/offers/{slug}", status_code=204)
async def admin_delete_offer(
    slug: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    """Une offre souscrite ne se supprime pas : elle se DÉPUBLIE. La supprimer
    couperait le lien entre un abonné et ce pour quoi il paie."""
    if await offer_reference(slug, conn):
        raise HTTPException(
            status_code=409,
            detail=(
                f"L'offre {slug!r} est portée par au moins un abonnement — "
                "la dépublier plutôt que la supprimer"
            ),
        )
    if not await delete_offer(slug, conn):
        raise HTTPException(status_code=404, detail=f"Offre {slug!r} introuvable")
    log.info("billing_offer_deleted", slug=slug, actor=user.login)
