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
from ..db.provisioning_catalogue import charger_catalogue
from ..db.provisioning_runs import enregistrer, marquer
from .cible import Cible, resoudre_cible
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
    modèle de partage retenu, et lui seul. Le rattachement pend de
    l'ABONNEMENT (migration 118) — d'où `subscription_id` sur chaque méthode :
    sans lui, l'exécuteur ne saurait pas à qui la place revient.
    """

    async def creer_vm_dediee(
        self, *, subscription_id: str, owner_login: str, offer_slug: str, noeud: str, cible: Cible
    ) -> HostProvisionne: ...

    async def creer_host_mutualise(
        self, *, subscription_id: str, owner_login: str, offer_slug: str, cible: Cible
    ) -> HostProvisionne: ...

    async def assigner_host(
        self, *, subscription_id: str, owner_login: str, offer_slug: str, host_name: str
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
    host_profiles: list[str],
    executeur: Executeur,
) -> Resultat:
    """Traite un événement d'abonnement de bout en bout.

    Le rejeu est traité en deux endroits, et les deux comptent : le décideur
    refuse de reprovisionner une offre qui a déjà sa machine, et le registre
    refuse une seconde tentative pour le même événement. Le premier protège
    contre l'activation qui suit un essai, le second contre le webhook renvoyé.

    `host_profiles` vient de l'offre, DANS SON ORDRE DE PRIORITÉ : c'est de lui
    qu'on tire le gabarit à monter. Passé par l'appelant comme `hosting_type`,
    et pour la même raison — ce module séquence, il ne relit pas le catalogue
    commercial.
    """
    # Cle d'idempotence : l'ABONNEMENT. Le couple (compte, offre) confondait
    # deux souscriptions legitimes a la meme offre (migration 118).
    deja = await a_deja_une_machine(subscription_id, conn)
    pool = await pool_mutualise(conn) if hosting_type == "mutualise" else []
    cible = resoudre_cible(host_profiles, await charger_catalogue(conn))
    decision = decider(
        evenement=evenement,
        hosting_type=hosting_type,
        deja_provisionne=deja,
        pool=pool,
        cible=cible,
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

    if decision.action == "impossible":
        # Il fallait monter une machine et aucun gabarit ne s'est résolu. On ne
        # tente rien — il n'y a rien à tenter — mais l'écart est un ÉCHEC, pas
        # un « fait » : le client a payé, et cette ligne est ce qui le rend
        # listable et rejouable une fois la configuration réparée.
        await marquer(run_id, "echec", conn, erreur=decision.motif)
        _log.error(
            "provisioning_sans_cible",
            run_id=run_id,
            owner=owner_login,
            offer=offer_slug,
            motif=decision.motif,
        )
        return Resultat(
            run_id=run_id, decision=decision, state="echec", erreur=decision.motif
        )

    await marquer(run_id, "en_cours", conn)
    try:
        provisionne = await _executer(decision, executeur, subscription_id, owner_login, offer_slug)
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
    decision: Decision,
    executeur: Executeur,
    subscription_id: str,
    owner_login: str,
    offer_slug: str,
) -> HostProvisionne:
    if decision.action == "creer_vm_dediee":
        # `decider` ne rend cette action qu'avec une cible : l'absence ici
        # signalerait un verdict incohérent, pas une VM à monter au hasard.
        if decision.cible is None:
            raise RuntimeError("verdict creer_vm_dediee sans cible")
        return await executeur.creer_vm_dediee(
            subscription_id=subscription_id,
            owner_login=owner_login,
            offer_slug=offer_slug,
            noeud=decision.noeud or "",
            cible=decision.cible,
        )
    if decision.action == "creer_host_mutualise":
        if decision.cible is None:
            raise RuntimeError("verdict creer_host_mutualise sans cible")
        return await executeur.creer_host_mutualise(
            subscription_id=subscription_id,
            owner_login=owner_login,
            offer_slug=offer_slug,
            cible=decision.cible,
        )
    if decision.action == "assigner_host":
        return await executeur.assigner_host(
            subscription_id=subscription_id,
            owner_login=owner_login,
            offer_slug=offer_slug,
            host_name=decision.host_name or "",
        )
    raise RuntimeError(f"action de provisioning inconnue : {decision.action!r}")
