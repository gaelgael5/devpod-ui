"""Souscription d'un forfait par l'utilisateur.

Ce que fait cette route, et surtout ce qu'elle ne fait pas.

Elle **crée l'abonnement**, puis **ouvre son paiement** — en deux routes et non
en une. L'abonnement existe déjà quand on demande à payer : un client qui
abandonne la page de paiement, ou dont la carte est refusée, reprend là où il en
était sans qu'on lui crée un second abonnement à chaque tentative.

Elle ne provisionne aucune machine et n'envoie aucun message : ces deux
chantiers ont leur étape dans l'ordre d'exécution. Une offre gratuite est
souscriptible de bout en bout et n'ouvre jamais de paiement.

L'ouverture prend un identifiant dans l'URL. Rien dans un UUID n'empêche d'en
réclamer un autre : l'appartenance se vérifie AVANT tout le reste, et le même
404 répond à « n'existe pas » et à « n'est pas à vous ».

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
from ..billing.canal import CanalDeVente, DemandePaiement, PaiementImpossible
from ..billing.canaux import CANAUX
from ..billing.eligibilite import SouscriptionRefusee, verifier
from ..billing.subscriptions import Subscription, fin_de_forfait
from ..config.store import load_global
from ..db.billing_catalog import (
    devise_par_defaut,
    devises_actives,
    get_provider,
    list_countries,
    list_country_providers,
)
from ..db.billing_offers import get_offer
from ..db.engine import get_conn
from ..db.subscriptions import creer, get, list_de, offres_deja_souscrites
from ..db.user_config import email_de
from ..secrets.system import reveal_system_secret

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


class OuverturePaiement(BaseModel):
    """Où envoyer le client pour qu'il paie."""

    model_config = ConfigDict(extra="forbid")

    url: str


@router.post("/subscriptions/{subscription_id}/paiement")
async def ouvrir_paiement(
    subscription_id: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> OuverturePaiement:
    """Ouvre la page de paiement d'un abonnement en attente.

    Séparée de la souscription, et pas fondue dedans : l'abonnement existe déjà
    quand on arrive ici. Un client qui abandonne la page de paiement, ou dont la
    carte est refusée, doit pouvoir reprendre sans re-souscrire — et sans qu'on
    lui crée un second abonnement à chaque tentative.
    """
    abonnement = await get(subscription_id, conn)
    # L'appartenance est vérifiée AVANT tout le reste, et le même 404 répond à
    # « n'existe pas » et « n'est pas à vous » : distinguer les deux dirait à un
    # curieux quels identifiants sont valides.
    if abonnement is None or abonnement.login != user.login:
        raise HTTPException(status_code=404, detail="Abonnement introuvable")

    if abonnement.state not in {"essai", "echec_paiement"}:
        # Un abonnement actif est déjà payé ; un résilié n'est pas repayable.
        raise HTTPException(
            status_code=409,
            detail="Cet abonnement n'attend pas de paiement.",
        )

    offre = await get_offer(abonnement.offer_slug, conn)
    if offre is None:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    if offre.is_free:
        # Pas une erreur de l'utilisateur : une offre gratuite n'a simplement
        # aucun paiement à ouvrir.
        raise HTTPException(status_code=409, detail="Cette offre est gratuite.")

    canal, cle_api = await _canal_et_clef(abonnement.provider_slug, conn)
    base = load_global().server.external_url.rstrip("/")
    assert offre.duration_days is not None  # garanti par `verifier` a la souscription
    demande = DemandePaiement(
        subscription_id=abonnement.id,
        libelle=offre.label or offre.slug,
        devise=abonnement.currency,
        # INSTANTANÉ figé à la souscription, jamais relu au catalogue : le prix
        # affiché au client est celui qu'il doit payer, même si le tarif a
        # changé entre-temps.
        montant_minor=abonnement.amount_minor,
        duree_jours=offre.duration_days,
        reconduction=offre.tacite_reconduction,
        # Pré-remplit la page de paiement. Vide si le compte n'a pas d'adresse
        # connue : le fournisseur la demandera lui-même, il en a besoin pour le
        # reçu.
        email=await email_de(user.login, conn),
        url_succes=f"{base}/forfaits/retour?abonnement={abonnement.id}",
        url_abandon=f"{base}/forfaits",
    )

    try:
        url = await canal.ouvrir_paiement(demande, cle_api)
    except PaiementImpossible as exc:
        # Le motif du fournisseur est journalisé, pas rendu : il décrit notre
        # requête, et l'utilisateur n'a rien à en faire.
        log.error(
            "paiement_ouverture_refusee",
            subscription_id=abonnement.id,
            provider=abonnement.provider_slug,
            raison=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail="Le canal de paiement n'a pas pu ouvrir la page. Réessayez.",
        ) from exc

    log.info(
        "paiement_ouvert",
        subscription_id=abonnement.id,
        provider=abonnement.provider_slug,
        by=user.login,
    )
    return OuverturePaiement(url=url)


async def _canal_et_clef(
    provider_slug: str | None, conn: AsyncConnection
) -> tuple[CanalDeVente, str]:
    """Adaptateur du canal et sa clef d'API, ou 409 si le canal n'est pas prêt."""
    provider = await get_provider(provider_slug, conn) if provider_slug else None
    canal = CANAUX.get(provider.kind) if provider else None
    if provider is None or canal is None:
        raise HTTPException(
            status_code=409,
            detail="Aucun canal de paiement n'est configuré pour cet abonnement.",
        )
    if not provider.enabled:
        raise HTTPException(status_code=409, detail="Ce canal de paiement est désactivé.")
    try:
        cle_api = await reveal_system_secret(provider.secret_slug, conn)
    except Exception as exc:  # noqa: BLE001 — secret absent ou coffre indisponible
        log.error("paiement_clef_illisible", provider=provider.slug, slug=provider.secret_slug)
        raise HTTPException(
            status_code=409,
            detail="La clef du canal de paiement est introuvable.",
        ) from exc
    return canal, cle_api
