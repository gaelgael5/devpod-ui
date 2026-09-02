"""Souscription d'un forfait par l'utilisateur.

Ce que fait cette route, et surtout ce qu'elle ne fait pas.

Elle **crée l'abonnement**, et rien d'autre. Elle ne prend aucun paiement, ne
provisionne aucune machine et n'envoie aucun message : chacun de ces trois
chantiers a son étape dans l'ordre d'exécution. Une offre gratuite est donc
d'ores et déjà souscriptible de bout en bout ; une offre payante s'arrête
proprement au seuil du paiement, avec un abonnement en attente.

Le PAYS décide de la taxe. Il est pré-rempli depuis l'en-tête `CF-IPCountry` que
Cloudflare pose lui-même, mais c'est le choix du client qui est enregistré : une
déduction par adresse IP se trompe derrière un VPN ou un proxy d'entreprise, et
elle n'établit pas à elle seule le lieu de consommation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..billing.eligibilite import SouscriptionRefusee, verifier
from ..billing.subscriptions import Subscription, fin_de_forfait
from ..db.billing_catalog import (
    devise_par_defaut,
    devises_actives,
    list_countries,
    list_country_providers,
)
from ..db.billing_offers import get_offer
from ..db.engine import get_conn
from ..db.subscriptions import creer, list_de, offres_deja_souscrites

router = APIRouter(tags=["subscriptions"])
log = structlog.get_logger(__name__)


class DemandeSouscription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_slug: str
    #: Pays retenu par le CLIENT. Pré-rempli par la déduction, jamais imposé
    #: par elle : c'est lui qui fait foi.
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    #: Devise choisie. Absente = devise par défaut du catalogue.
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class PaysOuvert(BaseModel):
    """Un pays où l'on vend, tel que l'écran doit le proposer."""

    model_config = ConfigDict(extra="forbid")

    code: str
    label: str


class ContexteSouscription(BaseModel):
    """Ce qu'il faut à l'écran d'engagement pour se pré-remplir."""

    model_config = ConfigDict(extra="forbid")

    #: Déduit de la connexion, `None` si la déduction n'est pas fiable.
    pays_devine: str | None
    #: Pays ACTIVÉS uniquement : proposer un pays où l'on ne vend pas mènerait
    #: droit à un refus, après que le client a choisi.
    pays: list[PaysOuvert]
    devise_par_defaut: str | None
    devises: list[str]


def _pays_devine(request: Request) -> str | None:
    """Pays déduit de la connexion, ou `None`.

    `CF-IPCountry` est posé par Cloudflare, devant le tunnel. On ne l'accepte
    qu'à la forme attendue : un en-tête forgé ne doit pas décider d'un taux de
    TVA, et il ne sert de toute façon qu'à PRÉ-REMPLIR — le client confirme.

    `XX` (inconnu) et `T1` (réseau Tor) sont des réponses de Cloudflare, pas des
    pays : elles se lisent « on ne sait pas ».
    """
    valeur = (request.headers.get("cf-ipcountry") or "").strip().upper()
    if len(valeur) != 2 or not valeur.isalpha() or valeur in {"XX", "T1"}:
        return None
    return valeur


@router.get("/subscriptions/contexte")
async def contexte_souscription(
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> ContexteSouscription:
    ouverts = [p for p in await list_countries(conn) if p.enabled]
    return ContexteSouscription(
        pays_devine=_pays_devine(request),
        pays=[PaysOuvert(code=p.code, label=p.label) for p in ouverts],
        devise_par_defaut=await devise_par_defaut(conn),
        devises=await devises_actives(conn),
    )


@router.get("/subscriptions")
async def mes_souscriptions(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, object]]:
    return [s.model_dump(mode="json") for s in await list_de(user.login, conn)]


@router.post("/subscriptions", status_code=201)
async def souscrire(
    body: DemandeSouscription,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    offre = await get_offer(body.offer_slug, conn)
    if offre is None:
        raise HTTPException(status_code=404, detail=f"Offre {body.offer_slug!r} introuvable")

    devise = body.currency or await devise_par_defaut(conn)
    if devise is None:
        raise HTTPException(
            status_code=409,
            detail="Aucune devise n'est configurée : la souscription est impossible.",
        )

    liens = await list_country_providers(conn, country_code=body.country_code)
    try:
        verifier(
            offre,
            offres_deja_souscrites=await offres_deja_souscrites(user.login, conn),
            devise=devise,
            devises_actives=set(await devises_actives(conn)),
            providers_du_pays={lien.provider_slug for lien in liens},
            pays=body.country_code,
        )
    except SouscriptionRefusee as exc:
        # 409 et non 400 : la demande est bien formée, c'est l'état du compte ou
        # du catalogue qui s'y oppose. Le message est affichable tel quel.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    prix = offre.prix(devise)
    maintenant = datetime.now(UTC)
    # `duration_days` est garanti non nul par `verifier` — sans terme, l'offre
    # n'est pas souscriptible.
    assert offre.duration_days is not None
    abonnement = Subscription(
        id=str(uuid.uuid4()),
        login=user.login,
        offer_slug=offre.slug,
        provider_slug=None if offre.is_free else offre.provider_slug,
        # `essai` : tout forfait commence borné par son terme. L'`activation`
        # viendra du canal de paiement, quand il existera ; une offre gratuite
        # n'en recevra jamais et s'arrêtera à son échéance.
        state="essai",
        country_code=body.country_code,
        currency=devise,
        # INSTANTANÉ du prix : le catalogue évoluera, cet abonné garde le sien.
        amount_minor=0 if offre.is_free or prix is None else prix.amount_minor,
        ends_at=fin_de_forfait(maintenant, offre.duration_days),
    )
    await creer(abonnement, conn)
    log.info(
        "souscription_creee",
        subscription_id=abonnement.id,
        offer=offre.slug,
        by=user.login,
        pays=abonnement.country_code,
        gratuite=offre.is_free,
    )
    return abonnement.model_dump(mode="json")
