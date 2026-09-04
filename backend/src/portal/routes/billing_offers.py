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
from ..db.billing_catalog import (
    devise_par_defaut,
    devises_actives,
    get_country,
    get_provider,
)
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
from ..db.host_profiles import get_host_profile

router = APIRouter(tags=["billing-offers"])
log = structlog.get_logger(__name__)

#: Routes servies SANS authentification. Montees a la racine, hors du prefixe
#: `/admin` : la page publique des forfaits doit etre lisible par quelqu'un qui
#: n'a pas encore de compte — c'est sa raison d'etre.
router_public = APIRouter(tags=["billing-offers"])


class OffrePubliee(BaseModel):
    """Ce qu'un visiteur ANONYME a le droit de savoir d'une offre.

    Une LISTE BLANCHE, et non un `model_dump()` de `Offer`. Le modele porte
    aussi `variables` (gabarit de VM, capacite des hosts), `provider_slug` et
    les profils de host : de l'infrastructure, qui n'a rien a faire sur une page
    ouverte a tous. Une liste blanche se relit ; une liste noire s'oublie au
    prochain champ ajoute au modele — et la fuite est alors silencieuse.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    titles: dict[str, str]
    descriptions: dict[str, str]
    hosting_type: str
    #: En mutualise : quota personnel du souscripteur, `None` = illimite. En
    #: dedie : plafond OPPOSABLE par machine — min(capacite declaree par le
    #: profil de host, quota de l'offre) — et `None` = NON RENSEIGNE, que la
    #: page n'affiche pas : une machine « illimitee » n'existe pas.
    max_workspaces: int | None
    max_hosts_dedies: int | None
    is_free: bool
    duration_days: int | None
    #: Au terme, le forfait repart-il ? Information materielle avant de
    #: s'engager : elle dit si le client sera preleve a nouveau.
    tacite_reconduction: bool
    #: Ce forfait est-il reserve a une souscription par compte ?
    une_par_compte: bool
    #: Devise par defaut du catalogue. `None` si aucune n'est designee ou si
    #: celle qui l'est a ete desactivee.
    currency: str | None
    #: Montant TEL QU'IL EST SAISI, en unites mineures. `None` quand l'offre n'a
    #: pas de prix dans cette devise : la page l'affiche alors sans prix plutot
    #: que de convertir depuis une autre devise a un taux qui ferait diverger
    #: l'affiche du debite.
    amount_minor: int | None
    #: Sens du montant. AUCUNE taxe n'est calculee ici : sans pays connu, un TTC
    #: serait un prix faux, et un prix faux est pire qu'un prix absent.
    prices_include_tax: bool


async def _plafond_dedie(offre: Offer, conn: AsyncConnection) -> int | None:
    """Plafond de workspaces par machine réellement opposable, ou `None`.

    Même arbitrage que `ownership.limite_effective` : la capacité déclarée par
    le profil de host est la contrainte dure, le quota de l'offre une borne
    commerciale — le plus bas des deux fait foi. Le provisioning pouvant
    retomber sur n'importe quel profil de la liste, on promet ce que le moins
    capable garantit, pas ce que le meilleur offre.

    `None` = rien de déclaré nulle part. Ce n'est pas « illimité » : c'est un
    trou de configuration, et la page publique ne doit rien en dire.
    """
    bornes = [offre.max_workspaces] if offre.max_workspaces is not None else []
    for slug in offre.host_profiles:
        profil = await get_host_profile(slug, conn)
        capacite = profil.capacity_workspaces() if profil else None
        if capacite is not None:
            bornes.append(capacite)
    return min(bornes) if bornes else None


def _vue_publique(offre: Offer, devise: str | None, max_workspaces: int | None) -> OffrePubliee:
    prix = offre.prix(devise) if devise else None
    return OffrePubliee(
        slug=offre.slug,
        titles=dict(offre.titles),
        descriptions=dict(offre.descriptions),
        hosting_type=offre.hosting_type,
        max_workspaces=max_workspaces,
        max_hosts_dedies=offre.max_hosts_dedies,
        is_free=offre.is_free,
        duration_days=offre.duration_days,
        tacite_reconduction=offre.tacite_reconduction,
        une_par_compte=offre.une_par_compte,
        currency=devise,
        amount_minor=None if prix is None else prix.amount_minor,
        prices_include_tax=offre.prices_include_tax,
    )


@router_public.get("/offers")
async def list_public_offers(
    conn: AsyncConnection = Depends(get_conn),
) -> list[OffrePubliee]:
    """Offres PUBLIEES, pour la page publique des forfaits.

    `published_only=True` n'est pas un confort d'affichage : une offre non
    publiee est un brouillon ou une offre retiree du catalogue. La servir la
    rendrait souscriptible par quiconque en devine l'existence.
    """
    devise = await devise_par_defaut(conn)
    offres = await list_offers(conn, published_only=True)
    vues = []
    for offre in offres:
        # En dedie, le plafond affiche vient du profil de host : une machine a
        # une capacite, « illimite » n'existe pas. En mutualise, le champ reste
        # le quota personnel de l'offre.
        plafond = (
            await _plafond_dedie(offre, conn)
            if offre.hosting_type == "dedie"
            else offre.max_workspaces
        )
        vues.append(_vue_publique(offre, devise, plafond))
    return vues


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

    # Un profil inconnu partirait se faire refuser par la clé étrangère, en 500
    # et sans nommer le fautif. On le dit ici, avec son slug.
    for profil in body.host_profiles:
        if await get_host_profile(profil, conn) is None:
            raise HTTPException(status_code=422, detail=f"Profil de host {profil!r} introuvable")

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
        if not body.host_profiles:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Offre non publiable : aucun profil de host — rien ne dirait "
                    "quelle machine ouvrir à la souscription, et l'échec "
                    "tomberait après le paiement"
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
