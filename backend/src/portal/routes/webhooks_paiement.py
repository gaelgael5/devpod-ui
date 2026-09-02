"""Réception des webhooks d'un canal de vente.

**Route non authentifiée**, la deuxième du portail hors du flux OIDC. Sa seule
protection est la signature — il n'y a ni session, ni jeton, ni RBAC. Tout ce
qui arrive ici vient de l'extérieur et doit être traité comme tel.

Quatre invariants, et aucun n'est décoratif.

1. **Le corps brut, jamais re-sérialisé.** La signature porte sur les octets
   reçus. Un proxy qui reformate le JSON invalide toutes les signatures, et le
   symptôme — « signature invalide » sur des webhooks parfaitement valides — est
   pénible à rapporter à sa cause.
2. **Signature d'abord, lecture ensuite.** On ne désérialise rien avant d'avoir
   authentifié : le contenu d'une charge non signée n'a aucune valeur.
3. **L'idempotence est portée par la base**, pas par une lecture préalable. Un
   fournisseur réémet souvent en rafale, et le temps entre un `SELECT` et un
   `INSERT` suffit à laisser passer les deux.
4. **On répond 200 à ce qu'on ignore.** Un événement inconnu ou orphelin n'est
   pas une erreur de l'appelant : rendre une erreur ferait réessayer le
   fournisseur indéfiniment, puis désactiver le point de terminaison.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.canal import CanalDeVente, SignatureInvalide
from ..billing.canaux.stripe import CanalStripe
from ..billing.models import PaymentProvider
from ..billing.subscriptions import (
    Subscription,
    SubscriptionEvent,
    TransitionRefusee,
    appliquer,
)
from ..db.billing_catalog import get_provider
from ..db.engine import get_conn
from ..db.subscription_events import enregistrer
from ..db.subscriptions import enregistrer_etat, get, par_identifiant_fournisseur
from ..secrets.system import reveal_system_secret

router = APIRouter(tags=["webhooks"])
log = structlog.get_logger(__name__)

#: Un adaptateur par `PaymentProvider.kind`. Ajouter un canal, c'est ajouter une
#: entrée ici — le reste du portail continue de parler des cinq événements.
CANAUX: dict[str, CanalDeVente] = {"stripe": CanalStripe()}

#: Au-delà, on refuse de lire. Un webhook de cycle d'abonnement pèse quelques
#: kilo-octets ; accepter un corps arbitraire sur une route ouverte serait
#: offrir de la mémoire à qui la demande.
TAILLE_MAX = 512 * 1024


@router.post("/webhooks/paiement/{provider_slug}", status_code=200)
async def recevoir(
    provider_slug: str,
    request: Request,
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    provider = await get_provider(provider_slug, conn)
    canal = CANAUX.get(provider.kind) if provider else None
    if provider is None or canal is None:
        # 404 : le canal n'existe pas. C'est la SEULE erreur qu'on rend à
        # l'extérieur, et elle ne dit rien de plus que « ce chemin n'existe
        # pas » — un scan ne doit pas apprendre quels slugs sont valides.
        raise HTTPException(status_code=404, detail="Canal inconnu")

    corps = await request.body()
    if len(corps) > TAILLE_MAX:
        raise HTTPException(status_code=413, detail="Charge trop volumineuse")

    secret = await _secret_de_signature(provider, conn)
    try:
        canal.verifier_signature(corps, request.headers, secret, datetime.now(UTC))
    except SignatureInvalide:
        # Journalisé sans la charge : elle n'est pas authentifiée, la recopier
        # reviendrait à écrire dans nos journaux ce qu'un inconnu a envoyé.
        log.warning("webhook_signature_invalide", provider=provider_slug, taille=len(corps))
        raise HTTPException(status_code=400, detail="Signature invalide") from None

    try:
        charge = json.loads(corps)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Charge illisible") from None
    if not isinstance(charge, dict):
        raise HTTPException(status_code=400, detail="Charge illisible")

    evenement = canal.normaliser(charge)
    if evenement is None:
        # Le fournisseur émet quantité d'événements dont aucun ne nous regarde.
        return {"statut": "ignore"}
    evenement = evenement.model_copy(update={"provider_slug": provider_slug})

    abonnement = await _resoudre(evenement, charge, conn)

    # L'écriture du journal TRANCHE l'idempotence, et elle précède la
    # transition : dans cet ordre, un rejeu ne peut pas la rejouer.
    if not await enregistrer(evenement, abonnement.id if abonnement else None, conn):
        log.info(
            "webhook_deja_traite",
            provider=provider_slug,
            event_id=evenement.provider_event_id,
        )
        return {"statut": "deja_traite"}

    if abonnement is None:
        # Authentique, mais rattaché à rien de connu. Tracé — c'est un écart
        # qui mérite d'être vu — et accepté, pour ne pas faire réessayer.
        log.warning(
            "webhook_abonnement_introuvable",
            provider=provider_slug,
            event_id=evenement.provider_event_id,
            kind=evenement.kind,
        )
        return {"statut": "orphelin"}

    try:
        maj = appliquer(abonnement, evenement, datetime.now(UTC))
    except TransitionRefusee as exc:
        # L'événement est réel mais l'abonnement n'est pas dans un état qui
        # l'accepte — un renouvellement sur un abonnement résilié, par exemple.
        # Il reste journalisé : c'est justement ce qu'on voudra relire.
        log.warning(
            "webhook_transition_refusee",
            provider=provider_slug,
            event_id=evenement.provider_event_id,
            subscription_id=abonnement.id,
            raison=str(exc),
        )
        return {"statut": "refuse"}

    await enregistrer_etat(maj, conn)
    log.info(
        "webhook_applique",
        provider=provider_slug,
        event_id=evenement.provider_event_id,
        subscription_id=abonnement.id,
        kind=evenement.kind,
        etat=maj.state,
    )
    return {"statut": "applique"}


async def _secret_de_signature(provider: PaymentProvider, conn: AsyncConnection) -> str:
    """Secret de signature du canal, ou chaîne vide s'il n'est pas configuré.

    Vide fait échouer la vérification, et c'est voulu : un canal sans secret
    n'authentifie rien, et l'ouvrir « en attendant » ouvrirait la route.
    """
    config = provider.config or {}
    slug = config.get("webhook_secret_slug") if isinstance(config, dict) else None
    if not slug:
        return ""
    try:
        return await reveal_system_secret(str(slug), conn)
    except Exception:  # noqa: BLE001 — secret absent ou vault indisponible
        log.error("webhook_secret_illisible", slug=slug)
        return ""


async def _resoudre(
    evenement: SubscriptionEvent, charge: dict[str, object], conn: AsyncConnection
) -> Subscription | None:
    """Retrouve l'abonnement visé, par métadonnée puis par identifiant fournisseur."""
    if evenement.subscription_id:
        trouve = await get(evenement.subscription_id, conn)
        if trouve is not None:
            return trouve

    # Repli : l'identifiant du fournisseur, porté par l'objet de l'événement.
    donnees = charge.get("data")
    objet = donnees.get("object") if isinstance(donnees, dict) else None
    if not isinstance(objet, dict):
        return None
    # Sur une facture, l'abonnement est référencé ; sur une souscription, c'est
    # l'objet lui-même.
    reference = objet.get("subscription") or objet.get("id")
    return await par_identifiant_fournisseur(str(reference or ""), conn)
