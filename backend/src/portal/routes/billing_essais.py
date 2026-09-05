"""Essais gratuits offerts par l'admin.

Un essai offert est adossé à une SOUSCRIPTION de forfait — la décision de la
fiche. Pas un drapeau sur le compte : l'abonnement existe, en état `essai`,
borné par la date choisie, et le provisioning `debut_essai` est le même que
celui d'une souscription gratuite. Tout ce qui sait lire un abonnement (quotas,
historique, provisioning) fonctionne donc sans cas particulier.

Ce qu'un essai offert n'est PAS : une vente. Le montant instantané est nul, et
aucun canal de paiement n'y est rattaché — l'abonnement ne recevra jamais de
webhook. La conversion en payant passera par une souscription normale, où le
client choisit son pays et paie le tarif du jour.

L'appel est en LOT : la fiche demande d'offrir à un ou plusieurs comptes d'un
geste. Un refus pour un compte ne prive pas les autres — la réponse dit, compte
par compte, ce qui a été accordé et pourquoi le reste ne l'a pas été.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..billing.declencheur import lancer_provisioning
from ..billing.models import Offer
from ..billing.subscriptions import Subscription, SubscriptionEvent
from ..db.billing_catalog import devise_par_defaut
from ..db.billing_offers import get_offer
from ..db.engine import get_conn
from ..db.subscription_events import PREFIXE_ESSAI_ADMIN, enregistrer, essai_deja_offert
from ..db.subscriptions import creer, list_de
from ..db.user_config import user_exists_db

router = APIRouter(tags=["billing-essais"])
log = structlog.get_logger(__name__)


class DemandeEssais(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_slug: str
    #: Bénéficiaires. Un lot, jamais vide — la fiche demande le geste en masse.
    logins: list[str] = Field(min_length=1)
    #: Fin de l'essai, choisie par l'admin (les raccourcis vivent à l'écran).
    fin: datetime


class ResultatEssai(BaseModel):
    """L'issue pour UN compte : accordé, ou refusé avec son motif."""

    model_config = ConfigDict(extra="forbid")

    login: str
    accorde: bool
    motif: str = ""
    subscription_id: str | None = None


class ReponseEssais(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resultats: list[ResultatEssai]


async def _motif_de_refus(login: str, offre: Offer, conn: AsyncConnection) -> str | None:
    """Ce qui s'oppose à offrir CET essai à CE compte, ou `None`.

    L'ordre : d'abord ce qui tient au compte (inexistant), puis à son état
    (abonnement en cours), puis au garde-fou anti-abus (essai déjà offert).
    Un abonnement RÉSILIÉ ne bloque rien : c'est le scénario de rétention —
    offrir un essai à un ancien abonné pour qu'il revienne.
    """
    if not await user_exists_db(login, conn):
        return "Compte inconnu."
    for abonnement in await list_de(login, conn):
        if abonnement.offer_slug == offre.slug and abonnement.ouvert:
            return "Un abonnement à cette offre est déjà en cours sur ce compte."
    if await essai_deja_offert(login, offre.slug, conn):
        return "Ce compte a déjà bénéficié d'un essai offert sur cette offre."
    return None


async def _pays_du_compte(login: str, conn: AsyncConnection) -> str:
    """Le pays du dernier abonnement du compte, ou `ZZ` (inconnu).

    `ZZ` est un code de la plage à usage privé d'ISO 3166 : on ne DEVINE pas un
    pays — il porte la taxe, et un essai offert n'en calcule aucune. La
    conversion en payant le demandera au client, comme toute souscription.
    """
    abonnements = await list_de(login, conn)
    return abonnements[0].country_code if abonnements else "ZZ"


@router.post("/billing/essais")
async def offrir_des_essais(
    body: DemandeEssais,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> ReponseEssais:
    offre = await get_offer(body.offer_slug, conn)
    if offre is None:
        raise HTTPException(status_code=404, detail=f"Offre {body.offer_slug!r} introuvable")

    maintenant = datetime.now(UTC)
    fin = body.fin if body.fin.tzinfo else body.fin.replace(tzinfo=UTC)
    if fin <= maintenant:
        raise HTTPException(status_code=422, detail="La fin de l'essai est déjà passée.")

    # La devise ne sert qu'à l'instantané (montant nul), mais son absence
    # signale un catalogue pas prêt — même refus qu'à la souscription.
    devise = await devise_par_defaut(conn)
    if devise is None:
        raise HTTPException(
            status_code=409,
            detail="Aucune devise n'est configurée : le catalogue n'est pas prêt.",
        )

    resultats: list[ResultatEssai] = []
    for login in body.logins:
        motif = await _motif_de_refus(login, offre, conn)
        if motif is not None:
            resultats.append(ResultatEssai(login=login, accorde=False, motif=motif))
            continue
        abonnement = Subscription(
            id=str(uuid.uuid4()),
            login=login,
            offer_slug=offre.slug,
            # Aucun canal : cet abonnement ne recevra jamais de webhook. La
            # conversion en payant est une souscription NEUVE, pas une mutation
            # de celui-ci.
            provider_slug=None,
            state="essai",
            country_code=await _pays_du_compte(login, conn),
            currency=devise,
            # Un cadeau, pas une vente : l'instantané de prix est NUL.
            amount_minor=0,
            trial_end=fin,
            ends_at=fin,
        )
        await creer(abonnement, conn)
        await enregistrer(
            SubscriptionEvent(
                kind="debut_essai",
                provider_slug="portail",
                provider_event_id=f"{PREFIXE_ESSAI_ADMIN}{abonnement.id}",
                login=login,
            ),
            abonnement.id,
            conn,
        )
        # Même provisioning qu'une souscription gratuite : l'essai donne le
        # service tout de suite, et l'idempotence est portée par l'événement.
        lancer_provisioning(
            subscription_id=abonnement.id,
            provider_event_id=f"{PREFIXE_ESSAI_ADMIN}{abonnement.id}",
            evenement="debut_essai",
            owner_login=login,
            offer_slug=offre.slug,
            hosting_type=offre.hosting_type,
            host_profiles=list(offre.host_profiles),
        )
        log.info(
            "essai_offert",
            subscription_id=abonnement.id,
            offer=offre.slug,
            beneficiaire=login,
            fin=fin.isoformat(),
            actor=user.login,
        )
        resultats.append(ResultatEssai(login=login, accorde=True, subscription_id=abonnement.id))
    return ReponseEssais(resultats=resultats)
