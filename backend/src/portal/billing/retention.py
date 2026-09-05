"""Le balayeur de rétention : signaler, une fois, ce qui doit disparaître.

La fiche « Arrêt, rétention et destruction d'un workspace non payé » découpe le
chantier en trois couches : un SCRIPT (workspace ressources) qui arrête et
détruit, une API devpod qu'il appelle, et CE balayeur — qui ne détruit rien
lui-même. Il repère les abonnements en `echec_paiement`/`resilie` dont le délai
est écoulé et émet `subscription.retention_expired` vers les automates ; ce
sont eux qui agissent.

Une notification par ÉPISODE, jamais une par jour : la fiche nomme le double
déclenchement comme LE défaut interdit — détruire deux fois, ou détruire ce
qu'un paiement venait de rattraper. La réservation (`marquer_notifie`) et
l'émission se font épisode par épisode ; un abonnement rétabli entre-temps a
changé d'état et sort de la requête tout seul.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog

from .evenements import TYPE_RETENTION_EXPIREE, publier_evenement_abonnement
from .subscriptions import EventKind, Subscription

log = structlog.get_logger(__name__)

#: Kind du canal correspondant à chaque état surveillé (pour le journal et le
#: payload). L'événement émis est TYPE_RETENTION_EXPIREE dans les deux cas.
_KIND_PAR_ETAT: dict[str, EventKind] = {
    "echec_paiement": "echec_paiement",
    "resilie": "resiliation",
}


def cle_episode(abonnement: Subscription) -> str:
    """Clé de dédup de l'événement émis, stable pour un épisode donné."""
    quand = abonnement.state_changed_at.isoformat() if abonnement.state_changed_at else ""
    return f"retention:{abonnement.id}:{abonnement.state}:{quand}"


async def balayer(maintenant: datetime | None = None) -> int:
    """Une passe : repère les retards, réserve chaque épisode, émet l'événement.

    Rend le nombre d'événements émis. La réservation est écrite AVANT
    l'émission, dans sa propre transaction : si l'émission échoue, l'épisode est
    marqué sans événement — un écart visible en base et journalisé, préférable à
    l'inverse (un événement de destruction émis deux fois).
    """
    from ..config.store import load_global
    from ..db.engine import _get_engine
    from ..db.retention import abonnements_en_retard, marquer_notifie

    politique = load_global().billing.retention
    quand = maintenant or datetime.now(UTC)
    async with _get_engine().connect() as conn:
        en_retard = await abonnements_en_retard(conn, maintenant=quand, politique=politique)

    emis = 0
    for abonnement in en_retard:
        if abonnement.state_changed_at is None:  # pragma: no cover - NOT NULL en base
            continue
        async with _get_engine().begin() as conn:
            reserve = await marquer_notifie(
                conn,
                subscription_id=abonnement.id,
                state=abonnement.state,
                state_changed_at=abonnement.state_changed_at,
            )
            if not reserve:
                continue
            await publier_evenement_abonnement(
                _KIND_PAR_ETAT[abonnement.state],
                abonnement,
                provider_event_id=cle_episode(abonnement),
                conn=conn,
                type_evenement=TYPE_RETENTION_EXPIREE,
                complement={
                    "retention_jours": politique.delai_jours(abonnement.state),
                    "state_changed_at": abonnement.state_changed_at.isoformat(),
                },
            )
        emis += 1
        log.info(
            "retention_expiree_notifiee",
            subscription_id=abonnement.id,
            state=abonnement.state,
            owner=abonnement.login,
            offer=abonnement.offer_slug,
            delai_jours=politique.delai_jours(abonnement.state),
        )
    return emis


async def retention_sweep_loop(interval_s: float = 3600.0) -> None:
    """Boucle de fond : une passe par heure, TERMES d'abord, rétention ensuite.

    L'ordre n'est pas décoratif : la clôture d'un terme produit un résilié, et
    c'est la rétention qui le suivra — dans la même boucle, il entame son délai
    au passage suivant. Le rythme n'a pas d'importance métier (la dédup par
    épisode et par échéance garantit l'unicité), mais une passe horaire borne à
    une heure le retard entre l'échéance et le signal, sans attendre « demain ».
    """
    from .terme import clore_les_termes

    await asyncio.sleep(5)  # laisse le portail démarrer
    while True:
        try:
            clos = await clore_les_termes()
            if clos:
                log.info("terme_sweep_done", clos=clos)
        except Exception:
            log.warning("terme_sweep_failed", exc_info=True)
        try:
            emis = await balayer()
            if emis:
                log.info("retention_sweep_done", emis=emis)
        except Exception:
            log.warning("retention_sweep_failed", exc_info=True)
        # APRÈS la rétention : les épisodes déjà expirés viennent d'être
        # notifiés et sortent de la requête — l'avertissement ne vise que ce
        # qui expire dans les `avertissement_jours` à venir.
        try:
            from ..emails.service import balayer_avertissements

            await balayer_avertissements()
        except Exception:
            log.warning("avertissement_sweep_failed", exc_info=True)
        await asyncio.sleep(interval_s)
