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
from ..billing.declencheur import lancer_provisioning
from ..billing.eligibilite import CanalIndisponible, SouscriptionRefusee, verifier
from ..billing.evenements import publier_evenement_abonnement
from ..billing.subscriptions import (
    RepriseRefusee,
    Subscription,
    SubscriptionEvent,
    fin_de_forfait,
    reprendre,
)
from ..config.store import load_global
from ..db.billing_address import adresse_figee, figer_adresse, lire_adresse
from ..db.billing_catalog import (
    devise_par_defaut,
    devises_actives,
    get_provider,
    list_countries,
    list_country_providers,
)
from ..db.billing_offers import get_offer
from ..db.engine import get_conn
from ..db.subscription_events import enregistrer, historique_de
from ..db.subscriptions import (
    creer,
    enregistrer_etat,
    enregistrer_reprise,
    get,
    list_de,
    offres_deja_souscrites,
)
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
    #: Pays de l'adresse de facturation du compte, `None` sans adresse saisie.
    #: PRIORITAIRE sur la déduction pour pré-remplir : une adresse saisie est
    #: une meilleure preuve du lieu de consommation qu'une IP — et l'écran doit
    #: proposer d'emblée le seul pays que la souscription acceptera.
    pays_adresse: str | None
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
    adresse = await lire_adresse(user.login, conn)
    return ContexteSouscription(
        pays_devine=_pays_devine(request),
        pays_adresse=adresse.country if adresse else None,
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


@router.get("/subscriptions/historique")
async def mon_historique(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, object]]:
    """L'historique du compte, vu par son titulaire : ses ACHATS uniquement.

    Les entrées d'exploitation (`visibilite=operation`) ne lui sont jamais
    servies — c'est le filtre porté par l'entrée, pas une seconde requête.
    """
    return await historique_de(user.login, conn, achats_seulement=True)


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
        if isinstance(exc, CanalIndisponible):
            # Vente perdue sur un trou de configuration : le client n'y peut
            # rien, et l'exploitant doit le voir — pas la subir en silence.
            log.warning(
                "vente_perdue_pays_sans_canal",
                offer=offre.slug,
                pays=body.country_code,
                login=user.login,
            )
        # 409 et non 400 : la demande est bien formée, c'est l'état du compte ou
        # du catalogue qui s'y oppose. Le message est affichable tel quel.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Le pays de l'adresse et celui de la souscription ne peuvent pas diverger :
    # le pays décide de la taxe, l'adresse s'imprime sur la facture — les
    # laisser différer produirait une facture qui se contredit elle-même.
    adresse = await lire_adresse(user.login, conn)
    if adresse is not None and adresse.country != body.country_code:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Le pays choisi ({body.country_code}) ne correspond pas à celui de votre "
                f"adresse de facturation ({adresse.country}). Mettez votre adresse à jour, "
                "ou choisissez le pays correspondant."
            ),
        )

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
    if adresse is not None:
        # FIGÉE sur l'abonnement, comme le prix : celle qui a servi ne bouge
        # plus, même si le profil change ensuite.
        await figer_adresse(abonnement.id, adresse, conn)
    log.info(
        "souscription_creee",
        subscription_id=abonnement.id,
        offer=offre.slug,
        by=user.login,
        pays=abonnement.country_code,
        gratuite=offre.is_free,
    )
    if offre.is_free:
        # Une offre gratuite ne recevra jamais de webhook : son `debut_essai`
        # se déclenche ICI, en fond. L'identifiant d'événement est synthétique
        # et stable — un rejeu de cette route créerait un AUTRE abonnement, et
        # c'est le registre du provisioning qui garantit l'unicité par
        # événement. Les offres payantes, elles, provisionnent sur les
        # événements du canal de vente : donner la machine avant le paiement
        # reviendrait à la donner gratuitement.
        lancer_provisioning(
            subscription_id=abonnement.id,
            provider_event_id=f"souscription:{abonnement.id}",
            evenement="debut_essai",
            owner_login=user.login,
            offer_slug=offre.slug,
            hosting_type=offre.hosting_type,
            host_profiles=list(offre.host_profiles),
        )
        # L'événement applicatif du début d'essai : une offre gratuite ne
        # recevra jamais de webhook, il part donc d'ici, même clé de dédup que
        # le provisioning.
        await publier_evenement_abonnement(
            "debut_essai",
            abonnement,
            provider_event_id=f"souscription:{abonnement.id}",
            conn=conn,
        )
    return abonnement.model_dump(mode="json")


class DemandeReprise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Reprendre sur une AUTRE offre — le cas courant quand le catalogue a
    #: bougé. Absent = la même offre.
    offer_slug: str | None = None
    #: Devise du nouveau prix. Absente = devise par défaut du catalogue.
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


@router.post("/subscriptions/{subscription_id}/reprendre")
async def reprendre_abonnement(
    subscription_id: str,
    body: DemandeReprise,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    """Reprend un abonnement résilié : un ACTE COMMERCIAL NEUF.

    Le prix est REFIGÉ au tarif du jour, le terme repart pour une durée pleine,
    et l'éligibilité est revérifiée comme à une souscription — c'est ce qui
    interdit de « reprendre » une offre limitée à une par compte : il suffirait
    de résilier pour la renouveler indéfiniment. La reprise repart en `essai`,
    comme toute souscription : une offre payante attendra son paiement, une
    gratuite est servie tout de suite.
    """
    abonnement = await get(subscription_id, conn)
    # Même 404 pour « n'existe pas » et « n'est pas à vous ».
    if abonnement is None or abonnement.login != user.login:
        raise HTTPException(status_code=404, detail="Abonnement introuvable")

    slug = body.offer_slug or abonnement.offer_slug
    offre = await get_offer(slug, conn)
    if offre is None:
        raise HTTPException(status_code=404, detail=f"Offre {slug!r} introuvable")

    devise = body.currency or await devise_par_defaut(conn)
    if devise is None:
        raise HTTPException(
            status_code=409,
            detail="Aucune devise n'est configurée : la reprise est impossible.",
        )

    # Le pays reste celui FIGÉ sur l'abonnement : la reprise ne rejoue pas le
    # choix du lieu de consommation — changer de pays passe par une nouvelle
    # souscription.
    liens = await list_country_providers(conn, country_code=abonnement.country_code)
    try:
        verifier(
            offre,
            offres_deja_souscrites=await offres_deja_souscrites(user.login, conn),
            devise=devise,
            devises_actives=set(await devises_actives(conn)),
            providers_du_pays={lien.provider_slug for lien in liens},
            pays=abonnement.country_code,
        )
    except SouscriptionRefusee as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    prix = offre.prix(devise)
    maintenant = datetime.now(UTC)
    assert offre.duration_days is not None  # garanti par `verifier`
    try:
        maj = reprendre(
            abonnement,
            currency=devise,
            # Tarif DU JOUR : l'instantané d'origine protégeait l'abonné
            # pendant la vie de son abonnement, pas au-delà.
            amount_minor=0 if offre.is_free or prix is None else prix.amount_minor,
            moment=maintenant,
            offer_slug=offre.slug,
            en_essai=True,
            duration_days=offre.duration_days,
        )
    except RepriseRefusee as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Le canal suit l'offre reprise : une gratuite n'en a pas, une payante
    # prend le sien — l'ancien routait les webhooks d'un abonnement mort.
    maj = maj.model_copy(update={"provider_slug": None if offre.is_free else offre.provider_slug})

    await enregistrer_reprise(maj, conn)
    cle = f"reprise:{maj.id}:{maintenant.isoformat()}"
    await enregistrer(
        SubscriptionEvent(
            kind="debut_essai",
            provider_slug="portail",
            provider_event_id=cle,
            login=user.login,
        ),
        maj.id,
        conn,
    )
    await publier_evenement_abonnement("debut_essai", maj, provider_event_id=cle, conn=conn)
    if offre.is_free:
        # Une gratuite ne recevra jamais de webhook : son provisioning part
        # d'ici. L'orchestrateur décide s'il y a encore une machine à monter.
        lancer_provisioning(
            subscription_id=maj.id,
            provider_event_id=cle,
            evenement="debut_essai",
            owner_login=user.login,
            offer_slug=offre.slug,
            hosting_type=offre.hosting_type,
            host_profiles=list(offre.host_profiles),
        )
    log.info(
        "abonnement_repris",
        subscription_id=maj.id,
        offer=offre.slug,
        by=user.login,
        gratuite=offre.is_free,
    )
    return maj.model_dump(mode="json")


@router.post("/subscriptions/{subscription_id}/resilier")
async def resilier_abonnement(
    subscription_id: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    """Résilie un abonnement ouvert. La SORTIE qui rend « sans engagement » vrai.

    Une résiliation N'EST PAS une suppression de compte : l'abonnement passe
    `resilie` (état CLOS mais réversible — `reprendre()` le rouvre), le compte
    demeure, et le disque est conservé le temps du délai de rétention avant
    destruction. C'est la sémantique que le modèle porte déjà, cohérente avec la
    décision « résiliation en essai = arrêt immédiat ».

    Deux points RESTENT à ton arbitrage et ne sont donc pas tranchés ici :
    - **immédiat vs fin de période payée** : le modèle coupe le droit au service
      immédiatement (`Subscription.ouvert` devient faux). Un « je garde l'accès
      jusqu'au terme déjà payé » demanderait un mécanisme distinct ;
    - **remboursement au prorata** du mois entamé : aucun remboursement n'est
      émis ici — c'est un geste commercial séparé (fiche remboursements/litiges).

    Pour un abonnement payant, la reconduction est coupée chez le fournisseur :
    sans quoi il continuerait de prélever un service résilié.
    """
    abonnement = await get(subscription_id, conn)
    if abonnement is None or abonnement.login != user.login:
        raise HTTPException(status_code=404, detail="Abonnement introuvable")
    if not abonnement.ouvert:
        # Déjà résilié (ou clos) : rien à faire, et le dire plutôt que rejouer.
        raise HTTPException(status_code=409, detail="Cet abonnement n'est pas actif.")

    maintenant = datetime.now(UTC)
    evenement = SubscriptionEvent(
        kind="resiliation",
        provider_slug="portail",
        provider_event_id=f"resiliation_client:{abonnement.id}:{maintenant.isoformat()}",
        login=user.login,
    )
    from ..billing.subscriptions import appliquer

    maj = appliquer(abonnement, evenement, maintenant)
    await enregistrer(evenement, abonnement.id, conn)
    await enregistrer_etat(maj, conn)
    await publier_evenement_abonnement(
        "resiliation", maj, provider_event_id=evenement.provider_event_id, conn=conn
    )

    # Reconduction coupée chez le fournisseur pour un payant : best-effort, la
    # résiliation locale est déjà actée — un fournisseur injoignable ne doit pas
    # laisser l'abonné coincé « actif » de notre côté.
    if abonnement.provider_slug and abonnement.provider_subscription_id:
        try:
            canal, cle = await _canal_et_clef(abonnement.provider_slug, conn)
            await canal.couper_reconduction(abonnement.provider_subscription_id, cle)
        except Exception as exc:  # noqa: BLE001 — la coupure se retente, la résiliation est faite
            log.error(
                "resiliation_reconduction_non_coupee",
                subscription_id=abonnement.id,
                provider=abonnement.provider_slug,
                raison=str(exc),
            )

    log.info("abonnement_resilie", subscription_id=abonnement.id, by=user.login)
    return maj.model_dump(mode="json")


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
        # L'adresse FIGÉE de cet abonnement — pas celle, mouvante, du profil :
        # c'est elle qui a validé le pays de taxe à la souscription.
        adresse=await adresse_figee(abonnement.id, conn),
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
