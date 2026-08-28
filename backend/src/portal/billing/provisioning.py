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

from .ownership import HostingType
from .subscriptions import EventKind

#: Nœud Proxmox où atterrissent les VM dédiées. pve2 est hors jeu (GPU réservé).
NOEUD_DEDIE = "pve"

#: Les seuls événements qui provisionnent. Les autres — renouvellement, échec de
#: paiement, résiliation — ne créent rien : ils relèvent du cycle de vie, pas de
#: l'ouverture d'un accès.
EVENEMENTS_PROVISIONNANTS: frozenset[EventKind] = frozenset({"debut_essai", "activation"})

Action = Literal["rien", "assigner_host", "creer_host_mutualise", "creer_vm_dediee"]


class HostDisponible(BaseModel):
    """Un host du pool mutualisé et le nombre de places qu'il lui reste.

    `places_restantes` se calcule en amont par `ownership.capacite_restante` :
    ce module ne recompte pas les workspaces, il fait confiance au chiffre —
    mais il se méfie d'un négatif, qui signale une machine sur-souscrite après
    une réduction de capacité.
    """

    model_config = ConfigDict(extra="forbid")

    host_name: str
    places_restantes: int


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


def _meilleur_candidat(pool: list[HostDisponible]) -> HostDisponible | None:
    """Host le plus rempli parmi ceux qui ont encore de la place.

    Le tri secondaire sur le nom rend le choix déterministe : deux machines à
    égalité doivent donner la même réponse d'un appel à l'autre, sans quoi le
    rejeu d'un événement — qui est la norme avec des webhooks — ne serait plus
    idempotent.
    """
    candidats = [h for h in pool if h.places_restantes > 0]
    if not candidats:
        return None
    return min(candidats, key=lambda h: (h.places_restantes, h.host_name))


def decider(
    *,
    evenement: EventKind,
    hosting_type: HostingType,
    deja_provisionne: bool,
    pool: list[HostDisponible],
) -> Decision:
    """Que provisionner pour cette souscription, si tant est qu'il faille.

    `deja_provisionne` porte l'idempotence : c'est à l'appelant de savoir si
    l'abonnement a déjà sa machine — typiquement parce que `debut_essai` est
    passé avant `activation`.
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
        return Decision(
            action="creer_vm_dediee",
            noeud=NOEUD_DEDIE,
            motif=f"forfait dédié : création d'une VM sur {NOEUD_DEDIE}",
        )

    candidat = _meilleur_candidat(pool)
    if candidat is None:
        return Decision(
            action="creer_host_mutualise",
            motif=("aucun host mutualisé n'a de place" if pool else "le pool mutualisé est vide"),
        )
    return Decision(
        action="assigner_host",
        host_name=candidat.host_name,
        motif=(
            f"host {candidat.host_name} retenu — {candidat.places_restantes} place(s) libre(s), "
            "la plus remplie de celles qui conviennent"
        ),
    )
