"""Enchaînement du provisioning : décider, tracer, exécuter, marquer.

Ce module ne sait ni créer une VM ni assigner une place : il **séquence**. Ce
qui touche l'hyperviseur est derrière `Executeur`, une interface injectée — la
logique d'enchaînement se teste donc sans Proxmox, et l'adaptateur réel reste
une pièce remplaçable.

L'ordre des écritures n'est pas indifférent : **la trace est posée avant
l'exécution**. Une VM créée sans ligne de suivi est une machine orpheline que
personne ne réconcilie ; une ligne sans VM est un échec visible, qu'on peut
rejouer. Entre les deux fautes possibles, on choisit la réparable.

Une exécution qui échoue **ne remonte pas d'exception à l'appelant** : le
webhook doit répondre au provider, sinon celui-ci rejoue indéfiniment un
événement qui échouera pareil. L'échec est enregistré, listable, et rejouable
depuis l'administration.
"""

from __future__ import annotations

from typing import Protocol

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.host_pool import a_deja_une_machine, pool_mutualise
from ..db.provisioning_runs import enregistrer, marquer
from .ownership import HostingType
from .provisioning import Decision, decider
from .subscriptions import EventKind

_log = structlog.get_logger(__name__)


class HostProvisionne(BaseModel):
    """Ce que l'exécuteur rend après avoir agi.

    `capacity_workspaces` vient du profil de host utilisé : c'est l'exécuteur
    qui sait sur quel gabarit la machine a été montée. `None` = le profil ne la
    déclare pas — trou de configuration, pas machine infinie.
    """

    model_config = ConfigDict(extra="forbid")

    host_name: str
    capacity_workspaces: int | None = None


class Executeur(Protocol):
    """Ce que l'infrastructure doit savoir faire pour honorer un verdict.

    Chaque méthode est responsable de **persister le rattachement** qu'elle
    crée (propriété de la machine, place accordée) : c'est elle qui connaît le
    modèle de partage retenu, et lui seul.
    """

    async def creer_vm_dediee(
        self, *, owner_login: str, offer_slug: str, noeud: str
    ) -> HostProvisionne: ...

    async def creer_host_mutualise(
        self, *, owner_login: str, offer_slug: str
    ) -> HostProvisionne: ...

    async def assigner_host(
        self, *, owner_login: str, offer_slug: str, host_name: str
    ) -> HostProvisionne: ...


class Resultat(BaseModel):
    """Issue d'un traitement, pour l'appelant et pour le journal."""

    model_config = ConfigDict(extra="forbid")

    #: `None` quand l'événement avait déjà sa tentative (rejeu).
    run_id: int | None
    decision: Decision
    #: `decide` tant que rien n'a été tenté, sinon l'état final.
    state: str
    host_name: str | None = None
    erreur: str = ""


async def traiter(
    conn: AsyncConnection,
    *,
    subscription_id: str,
    provider_event_id: str,
    evenement: EventKind,
    owner_login: str,
    offer_slug: str,
    hosting_type: HostingType,
    executeur: Executeur,
) -> Resultat:
    """Traite un événement d'abonnement de bout en bout.

    Le rejeu est traité en deux endroits, et les deux comptent : le décideur
    refuse de reprovisionner une offre qui a déjà sa machine, et le registre
    refuse une seconde tentative pour le même événement. Le premier protège
    contre l'activation qui suit un essai, le second contre le webhook renvoyé.
    """
    deja = await a_deja_une_machine(owner_login, offer_slug, conn)
    pool = await pool_mutualise(conn) if hosting_type == "mutualise" else []
    decision = decider(
        evenement=evenement,
        hosting_type=hosting_type,
        deja_provisionne=deja,
        pool=pool,
    )

    run_id = await enregistrer(
        conn,
        subscription_id=subscription_id,
        provider_event_id=provider_event_id,
        kind=evenement,
        owner_login=owner_login,
        offer_slug=offer_slug,
        decision=decision,
    )
    if run_id is None:
        # Événement déjà traité : ne rien refaire, et le dire.
        _log.info(
            "provisioning_rejeu_ignore",
            subscription_id=subscription_id,
            provider_event_id=provider_event_id,
        )
        return Resultat(run_id=None, decision=decision, state="rejeu")

    if decision.action == "rien":
        await marquer(run_id, "fait", conn)
        return Resultat(run_id=run_id, decision=decision, state="fait")

    await marquer(run_id, "en_cours", conn)
    try:
        provisionne = await _executer(decision, executeur, owner_login, offer_slug)
    except Exception as exc:  # noqa: BLE001 — l'échec se trace, il ne remonte pas
        await marquer(run_id, "echec", conn, erreur=str(exc))
        _log.error(
            "provisioning_echec",
            run_id=run_id,
            action=decision.action,
            owner=owner_login,
            offer=offer_slug,
            error=str(exc),
            exc_info=True,
        )
        return Resultat(run_id=run_id, decision=decision, state="echec", erreur=str(exc))

    await marquer(run_id, "fait", conn)
    _log.info(
        "provisioning_fait",
        run_id=run_id,
        action=decision.action,
        host=provisionne.host_name,
        owner=owner_login,
        offer=offer_slug,
    )
    return Resultat(run_id=run_id, decision=decision, state="fait", host_name=provisionne.host_name)


async def _executer(
    decision: Decision, executeur: Executeur, owner_login: str, offer_slug: str
) -> HostProvisionne:
    if decision.action == "creer_vm_dediee":
        return await executeur.creer_vm_dediee(
            owner_login=owner_login, offer_slug=offer_slug, noeud=decision.noeud or ""
        )
    if decision.action == "creer_host_mutualise":
        return await executeur.creer_host_mutualise(owner_login=owner_login, offer_slug=offer_slug)
    if decision.action == "assigner_host":
        return await executeur.assigner_host(
            owner_login=owner_login, offer_slug=offer_slug, host_name=decision.host_name or ""
        )
    raise RuntimeError(f"action de provisioning inconnue : {decision.action!r}")
