"""Déclenchement du provisioning en tâche de fond.

Monter une VM prend des minutes ; ni la réponse d'un webhook ni celle d'une
souscription ne peuvent l'attendre — le fournisseur rejouerait sur timeout, et
le client regarderait un spinner. La tâche part donc en fond, et l'état vit dans
`provisioning_runs` : c'est lui qu'on lit, pas la tâche.

Les tâches sont **référencées** (jeu module + `add_done_callback`) : une tâche
asyncio sans référence peut être ramassée par le GC en plein vol — c'est la
panne décrite dans le ticket « Tâches asyncio fire-and-forget non référencées ».

Aucune exception ne s'échappe : l'orchestrateur trace déjà ses échecs dans le
registre ; ce qui casserait AVANT lui (moteur DB indisponible) est journalisé en
erreur — un provisioning perdu doit se voir, jamais se taire.
"""

from __future__ import annotations

import asyncio

import structlog

from .orchestration import traiter
from .ownership import HostingType
from .subscriptions import EventKind

log = structlog.get_logger(__name__)

_taches: set[asyncio.Task[None]] = set()


def lancer_provisioning(
    *,
    subscription_id: str,
    provider_event_id: str,
    evenement: EventKind,
    owner_login: str,
    offer_slug: str,
    hosting_type: HostingType,
    host_profiles: list[str],
) -> asyncio.Task[None]:
    """Lance le traitement d'un événement d'abonnement, sans attendre l'issue."""

    async def _travail() -> None:
        from ..db.engine import _get_engine
        from .executeur_proxmox import ExecuteurProxmox

        try:
            async with _get_engine().begin() as conn:
                resultat = await traiter(
                    conn,
                    subscription_id=subscription_id,
                    provider_event_id=provider_event_id,
                    evenement=evenement,
                    owner_login=owner_login,
                    offer_slug=offer_slug,
                    hosting_type=hosting_type,
                    host_profiles=host_profiles,
                    executeur=ExecuteurProxmox(),
                )
        except Exception:  # noqa: BLE001 — un provisioning perdu doit se voir
            log.error(
                "provisioning_declenchement_echec",
                subscription_id=subscription_id,
                provider_event_id=provider_event_id,
                kind=evenement,
                exc_info=True,
            )
            return
        log.info(
            "provisioning_declenche_termine",
            subscription_id=subscription_id,
            provider_event_id=provider_event_id,
            kind=evenement,
            state=resultat.state,
            host=resultat.host_name,
        )

    tache = asyncio.create_task(_travail())
    _taches.add(tache)
    tache.add_done_callback(_taches.discard)
    return tache
