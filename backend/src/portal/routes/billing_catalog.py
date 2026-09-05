"""Catalogue de facturation : pays, devises, canaux de paiement.

Ce sont les données qui décident de ce qu'on peut vendre, où, et par quel canal.
Réservé aux administrateurs — s'y tromper, c'est facturer un client au mauvais
taux ou dans la mauvaise devise.

Les refus sont posés ici plutôt qu'en base : la base sait dire non, elle ne sait
pas dire pourquoi à quelqu'un qui remplit un formulaire.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..billing.models import Country, CountryProvider, Currency, PaymentProvider
from ..db.billing_catalog import (
    delete_country,
    delete_provider,
    get_country,
    get_provider,
    list_countries,
    list_country_providers,
    list_currencies,
    list_providers,
    provider_reference,
    set_country_providers,
    set_currencies,
    upsert_country,
    upsert_provider,
)
from ..db.engine import get_conn

router = APIRouter(tags=["billing-catalog"])
log = structlog.get_logger(__name__)


async def _pays_ou_404(code: str, conn: AsyncConnection) -> Country:
    pays = await get_country(code, conn)
    if pays is None:
        raise HTTPException(status_code=404, detail=f"Pays {code!r} introuvable")
    return pays


# ─── Pays ────────────────────────────────────────────────────────────────────


@router.get("/billing/countries")
async def admin_list_countries(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return [p.model_dump() for p in await list_countries(conn)]


@router.put("/billing/countries/{code}")
async def admin_save_country(
    code: str,
    body: Country,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Crée ou remplace. Le code de l'URL fait foi : sans quoi un PUT sur `/FR`
    écraserait le pays désigné dans le corps."""
    if body.code != code:
        raise HTTPException(
            status_code=422,
            detail=f"code du corps ({body.code!r}) différent de celui de l'URL ({code!r})",
        )
    await upsert_country(body, conn)
    log.info("billing_country_saved", code=code, actor=user.login)
    return body.model_dump()


@router.delete("/billing/countries/{code}", status_code=204)
async def admin_delete_country(
    code: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await delete_country(code, conn):
        raise HTTPException(status_code=404, detail=f"Pays {code!r} introuvable")
    log.info("billing_country_deleted", code=code, actor=user.login)


# ─── Devises acceptees par l'application ─────────────────────────────────────


@router.get("/billing/currencies")
async def admin_list_currencies(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return [d.model_dump() for d in await list_currencies(conn)]


@router.put("/billing/currencies")
async def admin_set_currencies(
    body: list[Currency],
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Remplace le jeu de devises de l'application.

    Le jeu est GLOBAL : ce que la plateforme sait encaisser ne depend pas du
    pays de l'acheteur. Exactement une devise par defaut des que la liste n'est
    pas vide — zero laisserait le portail sans devise a proposer, deux
    rendraient le choix indetermine au moment de presenter un prix.
    """
    _valider_devises(body)
    await set_currencies(body, conn)
    log.info("billing_currencies_set", devises=[d.code for d in body], actor=user.login)
    return [d.model_dump() for d in body]


def _valider_devises(devises: list[Currency]) -> None:
    codes = [d.code for d in devises]
    doublons = sorted({c for c in codes if codes.count(c) > 1})
    if doublons:
        raise HTTPException(status_code=422, detail=f"devise répétée : {', '.join(doublons)}")
    if not devises:
        return
    defauts = [d.code for d in devises if d.is_default]
    if len(defauts) != 1:
        raise HTTPException(
            status_code=422,
            detail=(
                "exactement une devise par défaut est attendue — "
                f"{len(defauts)} désignée(s) : {', '.join(defauts) or 'aucune'}"
            ),
        )
    inactives = sorted(d.code for d in devises if d.is_default and not d.enabled)
    if inactives:
        raise HTTPException(
            status_code=422,
            detail=f"la devise par défaut doit être active : {', '.join(inactives)}",
        )


# ─── Canaux de paiement ──────────────────────────────────────────────────────


@router.get("/billing/providers")
async def admin_list_providers(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return [p.model_dump() for p in await list_providers(conn)]


@router.put("/billing/providers/{slug}")
async def admin_save_provider(
    slug: str,
    body: PaymentProvider,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Crée ou remplace.

    Le corps ne porte JAMAIS de secret : `secret_slug` désigne une entrée de la
    table des secrets. La conformité de `config` au `kind` est vérifiée par le
    modèle — une clé inconnue est refusée ici, pas découverte au premier paiement.
    """
    if body.slug != slug:
        raise HTTPException(
            status_code=422,
            detail=f"slug du corps ({body.slug!r}) différent de celui de l'URL ({slug!r})",
        )
    await upsert_provider(body, conn)
    log.info("billing_provider_saved", slug=slug, kind=body.kind, actor=user.login)
    return body.model_dump()


@router.delete("/billing/providers/{slug}", status_code=204)
async def admin_delete_provider(
    slug: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    """Un canal encore référencé ne se supprime pas : il se DÉSACTIVE
    (`enabled=false`). Le supprimer laisserait des abonnements sans moyen
    d'être prélevés."""
    if await provider_reference(slug, conn):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Le canal {slug!r} est référencé par une offre ou un abonnement — "
                "le désactiver plutôt que le supprimer"
            ),
        )
    if not await delete_provider(slug, conn):
        raise HTTPException(status_code=404, detail=f"Canal de paiement {slug!r} introuvable")
    log.info("billing_provider_deleted", slug=slug, actor=user.login)


# ─── Rattachement pays ↔ providers ───────────────────────────────────────────


@router.get("/billing/countries/{code}/providers")
async def admin_list_country_providers(
    code: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    await _pays_ou_404(code, conn)
    return [x.model_dump() for x in await list_country_providers(conn, country_code=code)]


@router.put("/billing/countries/{code}/providers")
async def admin_set_country_providers(
    code: str,
    body: list[CountryProvider],
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Remplace les canaux utilisables dans ce pays, par priorité croissante."""
    await _pays_ou_404(code, conn)
    etrangers = sorted({x.country_code for x in body if x.country_code != code})
    if etrangers:
        raise HTTPException(
            status_code=422,
            detail=f"rattachements visant un autre pays que {code!r} : {', '.join(etrangers)}",
        )
    slugs = [x.provider_slug for x in body]
    doublons = sorted({s for s in slugs if slugs.count(s) > 1})
    if doublons:
        raise HTTPException(
            status_code=422, detail=f"canal rattaché deux fois : {', '.join(doublons)}"
        )
    for slug in slugs:
        if await get_provider(slug, conn) is None:
            raise HTTPException(status_code=422, detail=f"Canal de paiement {slug!r} introuvable")
    await set_country_providers(code, body, conn)
    log.info("billing_country_providers_set", code=code, canaux=slugs, actor=user.login)
    return [x.model_dump() for x in body]
