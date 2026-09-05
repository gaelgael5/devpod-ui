"""Envoi des emails du cycle d'abonnement — composition, journal, dédup.

Le chemin nominal : une transition d'abonnement est actée → l'événement part
vers le bus → le mail suit le même fait générateur (`envoyer_email_cycle`,
appelé par `billing.evenements`). **Best-effort intégral** : aucun échec
d'email ne remonte jamais à la transition qui l'a déclenché.

Règles tenues ici :

- **pas d'email connu = pas d'envoi**, avec une ligne `echec` journalisée —
  jamais un envoi à vide ;
- **dédup par épisode** (`emails_envoyes`, contrainte d'unicité) : un webhook
  rejoué ou un double passage du balayeur n'envoie pas deux fois ;
- **payload figé** dans le journal : les dates limites y sont calculées depuis
  la politique de rétention du moment — la preuve de ce qui a été annoncé ;
- le template est bête : tout formatage se fait ici (`formatage.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.config import PolitiqueRetention
from ..billing.models import Offer
from ..billing.subscriptions import Subscription
from .formatage import formater_date, formater_montant, normaliser_culture, periodicite
from .listmonk_tx import ListmonkIndisponible, ListmonkTxClient
from .templates import nom_template

_log = structlog.get_logger(__name__)

#: Les kinds du cycle qui déclenchent un email. `remboursement` et `litige_*`
#: n'en ont pas tant que les arbitrages de la fiche chargebacks sont ouverts.
KINDS_AVEC_EMAIL = frozenset(
    {"debut_essai", "activation", "renouvellement", "echec_paiement", "resiliation"}
)


def composer_payload(
    *,
    kind: str,
    abonnement: Subscription,
    offre: Offer | None,
    culture: str,
    prenom_ou_login: str,
    base_url: str,
    politique: PolitiqueRetention,
    maintenant: datetime,
    produit: str,
    email_support: str,
    machines: list[str] | None = None,
) -> dict[str, Any]:
    """Le payload plat du template — chaînes prêtes, booléens, une liste.

    Fonction pure : tout ce qui dépend de l'heure ou de la politique est
    calculé ICI puis figé dans le journal par l'appelant.
    """
    cult = normaliser_culture(culture)
    base = base_url.rstrip("/")
    data: dict[str, Any] = {
        "prenom_ou_login": prenom_ou_login,
        "offre_label": _label_offre(offre, abonnement.offer_slug, cult),
        "prix_formate": formater_montant(abonnement.amount_minor, abonnement.currency, cult),
        "periodicite": periodicite(offre.duration_days if offre else None, cult),
        "produit": produit,
        "email_support": email_support,
        "lien_portail": base,
        "lien_abonnement": f"{base}/abonnement",
        "lien_paiement": f"{base}/abonnement",
        "lien_offres": f"{base}/forfaits",
        # Repli assumé tant que la facturation légale n'est pas livrée : la
        # page abonnement porte l'historique d'achats.
        "lien_facture": f"{base}/abonnement",
    }

    if kind == "debut_essai":
        fin = abonnement.trial_end or abonnement.ends_at or maintenant
        data["essai_fin_date"] = formater_date(fin, cult)
        data["essai_duree_jours"] = (
            offre.duration_days
            if offre and offre.duration_days
            else max(0, (fin - maintenant).days)
        )
        data["tacite_reconduction"] = bool(offre and offre.tacite_reconduction)
        data["recuperation_jours"] = politique.resiliation_jours
    elif kind in ("activation", "renouvellement"):
        data["paiement_date"] = formater_date(maintenant, cult)
        echeance = abonnement.current_period_end or abonnement.ends_at
        data["prochaine_echeance_date"] = formater_date(echeance, cult) if echeance else ""
        # Pas encore exposé par le canal de vente — rendu conditionnel.
        data["moyen_paiement"] = ""
    elif kind == "echec_paiement":
        data["echec_date"] = formater_date(maintenant, cult)
        data["echec_motif"] = ""  # idem : le canal peut se taire
        limite = maintenant + timedelta(days=politique.echec_paiement_jours)
        data["date_limite_recuperation"] = formater_date(limite, cult)
        data["recuperation_jours"] = politique.echec_paiement_jours
        data["avertissement_avant_destruction"] = politique.avertissement_jours > 0
    elif kind == "resiliation":
        fin_acces = abonnement.ends_at
        data["fin_acces_date"] = (
            formater_date(fin_acces, cult) if fin_acces and fin_acces > maintenant else ""
        )
        limite = maintenant + timedelta(days=politique.resiliation_jours)
        data["date_limite_recuperation"] = formater_date(limite, cult)
        data["recuperation_jours"] = politique.resiliation_jours
    elif kind == "avertissement_destruction":
        assise = abonnement.state_changed_at or maintenant
        echeance = assise + timedelta(days=politique.delai_jours(abonnement.state))
        data["etat"] = abonnement.state
        data["destruction_date"] = formater_date(echeance, cult)
        data["destruction_dans_jours"] = max(0, (echeance - maintenant).days)
        data["machines"] = machines or []
    return data


async def envoyer_email_cycle(
    kind: str,
    abonnement: Subscription,
    *,
    provider_event_id: str,
    conn: AsyncConnection,
    maintenant: datetime | None = None,
    client: ListmonkTxClient | None = None,
    machines: list[str] | None = None,
) -> bool:
    """Compose, réserve, envoie. Rend True si un email est parti. Ne lève jamais."""
    try:
        return await _envoyer(
            kind,
            abonnement,
            provider_event_id=provider_event_id,
            conn=conn,
            maintenant=maintenant or datetime.now(UTC),
            client=client,
            machines=machines,
        )
    except Exception:  # noqa: BLE001 — l'email ne casse jamais la transition
        _log.error(
            "email_cycle_failed",
            kind=kind,
            subscription_id=abonnement.id,
            exc_info=True,
        )
        return False


async def _envoyer(
    kind: str,
    abonnement: Subscription,
    *,
    provider_event_id: str,
    conn: AsyncConnection,
    maintenant: datetime,
    client: ListmonkTxClient | None,
    machines: list[str] | None,
) -> bool:
    from ..config.store import load_global
    from ..db.billing_offers import get_offer
    from ..db.emails_envoyes import marquer, reserver
    from ..db.user_config import contact_de
    from ..secrets.system import reveal_system_secret
    from ..settings import get_settings

    cfg = load_global()
    if not cfg.listmonk.enabled:
        return False

    settings = get_settings()
    email, culture, display_name = await contact_de(abonnement.login, conn)
    culture = normaliser_culture(culture)
    template = nom_template(kind, culture)
    offre = await get_offer(abonnement.offer_slug, conn)
    payload = composer_payload(
        kind=kind,
        abonnement=abonnement,
        offre=offre,
        culture=culture,
        prenom_ou_login=display_name or abonnement.login,
        base_url=cfg.server.external_url,
        politique=cfg.billing.retention,
        maintenant=maintenant,
        produit=settings.product_name,
        email_support=settings.support_email,
        machines=machines,
    )

    email_id = await reserver(
        conn,
        subscription_id=abonnement.id,
        kind=kind,
        dedup_key=provider_event_id,
        destinataire=email,
        culture=culture,
        template=template,
        data=payload,
    )
    if email_id is None:
        # Épisode déjà servi : rejeu de webhook ou double passage du balayeur.
        return False

    if not email:
        # Refuser d'envoyer, jamais envoyer à vide — et le rendre visible.
        await marquer(email_id, "echec", conn, erreur="email du compte inconnu")
        _log.warning("email_cycle_sans_destinataire", kind=kind, login=abonnement.login)
        return False

    if client is None:
        try:
            credential = await reveal_system_secret(cfg.listmonk.apikey_secret, conn)
        except KeyError:
            await marquer(
                email_id,
                "echec",
                conn,
                erreur=f"secret {cfg.listmonk.apikey_secret!r} introuvable",
            )
            _log.error("email_cycle_secret_illisible", slug=cfg.listmonk.apikey_secret)
            return False
        client = ListmonkTxClient(url=cfg.listmonk.url, credential=credential)

    try:
        await client.envoyer(template=template, email=email, data=payload)
    except ListmonkIndisponible as exc:
        await marquer(email_id, "echec", conn, erreur=str(exc)[:500])
        _log.error("email_cycle_envoi_echec", kind=kind, template=template, error=str(exc))
        return False
    await marquer(email_id, "envoye", conn)
    _log.info("email_cycle_envoye", kind=kind, subscription_id=abonnement.id, culture=culture)
    return True


async def balayer_avertissements(maintenant: datetime | None = None) -> int:
    """Le dernier filet : un email par épisode approchant sa destruction.

    Ne tourne que si `avertissement_jours > 0` (contrat de la fiche). Réutilise
    la requête de rétention avec une horloge avancée de N jours : ce qui sera
    « en retard » dans N jours est ce qu'il faut prévenir aujourd'hui. La dédup
    est portée par le journal (clé d'épisode) — un abonnement rétabli change
    d'état et sort de la requête tout seul.
    """
    from ..billing.retention import cle_episode
    from ..config.store import load_global
    from ..db.engine import _get_engine
    from ..db.retention import abonnements_en_retard
    from ..db.subscription_hosts import machines_de

    cfg = load_global()
    politique = cfg.billing.retention
    if not cfg.listmonk.enabled or politique.avertissement_jours <= 0:
        return 0
    quand = maintenant or datetime.now(UTC)
    horizon = quand + timedelta(days=politique.avertissement_jours)
    async with _get_engine().connect() as conn:
        candidats = await abonnements_en_retard(conn, maintenant=horizon, politique=politique)

    envoyes = 0
    for abonnement in candidats:
        async with _get_engine().begin() as conn:
            machines = await machines_de(abonnement.id, conn)
            if await envoyer_email_cycle(
                "avertissement_destruction",
                abonnement,
                provider_event_id=cle_episode(abonnement),
                conn=conn,
                maintenant=quand,
                machines=machines,
            ):
                envoyes += 1
    if envoyes:
        _log.info("avertissements_destruction_envoyes", count=envoyes)
    return envoyes


def _label_offre(offre: Offer | None, slug: str, culture: str) -> str:
    if offre is None:
        return slug
    return offre.titles.get(culture) or offre.label or slug
