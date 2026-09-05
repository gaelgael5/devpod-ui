"""Ce qu'une souscription fait naître : une VM dédiée, ou une place sur un host
mutualisé.

Ce module **décide, il n'exécute pas**. Il ne lit pas la base et n'appelle pas
Proxmox : l'appelant lui fournit l'état du parc, il rend un verdict motivé que
l'orchestrateur exécutera. Même parti pris que `ownership.py`, et pour les mêmes
raisons — les règles se testent alors sans base ni hyperviseur, et le motif du
choix se retrouve tel quel dans le journal le jour où l'on se demande pourquoi
telle machine a été ouverte.

Trois arbitrages sont figés ici :

1. **Deux événements provisionnent, et un seul provisioning.** `debut_essai`
   donne l'accès immédiatement, `activation` se déclenche au premier paiement
   réel. Ils font la même chose ; ce qui change, c'est le moment. D'où
   l'exigence d'idempotence : une activation qui suit un essai ne recrée rien.
2. **Le dédié va sur `pve`.** pve2 porte la RTX 4090, réservée à l'inférence
   LLM : aucune VM d'abonné n'y est créée.
3. **Le mutualisé remplit avant d'ouvrir.** On n'ouvre une machine que si
   aucune existante n'a de place — et entre plusieurs candidates, on prend la
   plus remplie de celles qui conviennent.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .cible import Cible
from .ownership import HostingType
from .subscriptions import EventKind

# `NOEUDS_EXCLUS` a disparu (il interdisait pve2 en dur). Le catalogue est la
# seule source de vérité : la garantie que pve2 (RTX 4090, réservée à
# l'inférence LLM) ne reçoit aucune VM d'abonné repose désormais UNIQUEMENT sur
# le fait de ne pas y déclarer d'hyperviseur — ce n'est plus le code qui la
# tient. Une exclusion en dur doublait la règle et aurait fini par la
# contredire.

#: Les seuls événements qui provisionnent. Les autres — renouvellement, échec de
#: paiement, résiliation — ne créent rien : ils relèvent du cycle de vie, pas de
#: l'ouverture d'un accès.
EVENEMENTS_PROVISIONNANTS: frozenset[EventKind] = frozenset({"debut_essai", "activation"})

Action = Literal[
    "rien",
    "assigner_host",
    "creer_host_mutualise",
    "creer_vm_dediee",
    # Il fallait monter une machine et aucun gabarit ne s'est resolu. Un
    # verdict a part entiere, et non "rien" : le client a paye, l'ecart doit
    # etre listable et rejouable au lieu d'etre tu.
    "impossible",
]


class HostDisponible(BaseModel):
    """Un host du pool mutualisé et le nombre de places qu'il lui reste.

    `places_restantes` se calcule en amont par `ownership.capacite_restante` :
    ce module ne recompte pas les workspaces, il fait confiance au chiffre —
    mais il se méfie d'un négatif, qui signale une machine sur-souscrite après
    une réduction de capacité.

    `None` = aucun plafond connu, parce que le profil de host ne déclare pas
    `capacity_workspaces`. C'est un trou de configuration, pas une machine
    infinie : la place existe peut-être, on n'en sait rien.
    """

    model_config = ConfigDict(extra="forbid")

    host_name: str
    places_restantes: int | None


class Decision(BaseModel):
    """Verdict : quoi faire, sur quelle machine, et pourquoi.

    `motif` est une phrase destinée au journal et à l'écran d'administration.
    Un provisioning qui se trompe de cible coûte cher — savoir *pourquoi* la
    cible a été choisie ne doit pas demander de relire le code.
    """

    model_config = ConfigDict(extra="forbid")

    action: Action
    motif: str
    #: Renseigné pour `assigner_host` uniquement.
    host_name: str | None = None
    #: Renseigné pour `creer_vm_dediee` uniquement.
    noeud: str | None = None
    #: Gabarit retenu — renseigné pour les deux actions qui MONTENT une machine.
    #: `assigner_host` n'en a pas : le gabarit de la machine d'accueil a été
    #: choisi le jour où elle a été montée.
    cible: Cible | None = None


def _meilleur_candidat(pool: list[HostDisponible]) -> HostDisponible | None:
    """Host le plus rempli parmi ceux qui ont encore de la place.

    Trois clés de tri, dans cet ordre :

    1. capacité connue d'abord — une machine dont on ignore le plafond n'est
       retenue qu'à défaut d'autre chose ;
    2. le moins de places restantes — remplir avant d'ouvrir ;
    3. le nom, pour trancher les égalités. Ce dernier point n'est pas
       cosmétique : un tirage instable rendrait le rejeu d'un événement — qui
       est la norme avec des webhooks — non idempotent.
    """
    candidats = [h for h in pool if h.places_restantes is None or h.places_restantes > 0]
    if not candidats:
        return None
    return min(
        candidats,
        key=lambda h: (
            h.places_restantes is None,
            h.places_restantes if h.places_restantes is not None else 0,
            h.host_name,
        ),
    )


def _sans_cible(contexte: str) -> Decision:
    """Verdict quand il fallait monter une machine sans qu'aucun gabarit ne se
    résolve.

    Le motif nomme la chaîne à réparer : l'administrateur doit savoir où
    regarder — l'offre ne liste aucun profil de host, ou ceux qu'elle liste ne
    mènent à aucun hyperviseur.
    """
    return Decision(
        action="impossible",
        motif=(
            f"{contexte} : aucun profil de host de l'offre ne mène à un hyperviseur "
            "— offre sans profil, profil supprimé, ou aucun hyperviseur déclaré "
            "pour son type"
        ),
    )


def decider(
    *,
    evenement: EventKind,
    hosting_type: HostingType,
    deja_provisionne: bool,
    pool: list[HostDisponible],
    cible: Cible | None = None,
) -> Decision:
    """Que provisionner pour cette souscription, si tant est qu'il faille.

    `deja_provisionne` porte l'idempotence : c'est à l'appelant de savoir si
    l'abonnement a déjà sa machine — typiquement parce que `debut_essai` est
    passé avant `activation`.

    `cible` est le gabarit résolu depuis les profils de host de l'offre (cf.
    `cible.resoudre_cible`). Elle n'est réclamée que par les actions qui MONTENT
    une machine ; assigner une place existante s'en passe.
    """
    if evenement not in EVENEMENTS_PROVISIONNANTS:
        return Decision(
            action="rien",
            motif=f"l'événement {evenement!r} ne provisionne pas",
        )

    if deja_provisionne:
        return Decision(
            action="rien",
            motif="l'abonnement a déjà sa machine — provisionner une seconde fois la doublerait",
        )

    if hosting_type == "dedie":
        if cible is None:
            return _sans_cible("forfait dédié")
        return Decision(
            action="creer_vm_dediee",
            noeud=cible.noeud,
            cible=cible,
            motif=(
                f"forfait dédié : création d'une VM sur {cible.noeud} "
                f"(hyperviseur {cible.hypervisor}, gabarit {cible.machine_profile} "
                f"via le profil de host {cible.host_profile})"
            ),
        )

    candidat = _meilleur_candidat(pool)
    if candidat is None:
        if cible is None:
            return _sans_cible("ouverture d'un host mutualisé")
        raison = "aucun host mutualisé n'a de place" if pool else "le pool mutualisé est vide"
        return Decision(
            action="creer_host_mutualise",
            cible=cible,
            motif=(
                f"{raison} : ouverture d'une machine {cible.machine_profile} "
                f"sur {cible.noeud} (hyperviseur {cible.hypervisor}, "
                f"profil de host {cible.host_profile})"
            ),
        )
    if candidat.places_restantes is None:
        return Decision(
            action="assigner_host",
            host_name=candidat.host_name,
            motif=(
                f"host {candidat.host_name} retenu par défaut — capacité non déclarée "
                "dans son profil de host, aucune autre machine n'avait de place"
            ),
        )
    return Decision(
        action="assigner_host",
        host_name=candidat.host_name,
        motif=(
            f"host {candidat.host_name} retenu — {candidat.places_restantes} place(s) libre(s), "
            "la plus remplie de celles qui conviennent"
        ),
    )
