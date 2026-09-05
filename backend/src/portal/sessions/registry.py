"""Registre process-global des terminaux vivants (websockets attachées).

Ce registre ne modélise PAS les sessions tmux (celles-ci vivent dans le
conteneur et sont énumérées à la demande), mais uniquement les terminaux
réellement *attachés* via un websocket ouvert sur cette instance du portail.
Il sert à marquer « attaché » les sessions dans l'agrégation.

Instance unique, boucle asyncio mono-thread : un simple dict module-global
suffit, aucun verrou requis (pas de préemption entre deux `await`). Les
fonctions sont idempotentes.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

Family = Literal["workspace", "host", "test"]


@dataclass(frozen=True)
class LiveTerminal:
    """Un terminal attaché (websocket ouvert) sur cette instance.

    `target` = ws_id pour un workspace, ou nom du host/VM sinon.
    `session` = nom de la session tmux pour un workspace, None pour host/test.
    `since` = timestamp monotone du rattachement (passé explicitement pour
    rester testable ; voir `new_terminal` pour l'horodatage automatique).
    """

    id: str
    family: Family
    target: str
    owner: str
    session: str | None = None
    since: float = field(default=0.0)


# Clé d'attachement utilisée pour marquer une session « attachée » dans l'agrégation.
AttachKey = tuple[Family, str, str | None]

_terminals: dict[str, LiveTerminal] = {}
# Terminaux fermés parce qu'un autre appareil a pris la main. Le pont y lit le
# motif avant de fermer le websocket, pour que le navigateur puisse afficher
# « ouvert ailleurs » plutôt qu'une coupure réseau anonyme.
_evicted: set[str] = set()
# Callback de fermeture par id : annule le pont websocket↔ssh du terminal.
# Séparé de LiveTerminal (qui reste un DTO pur, sérialisable) volontairement.
_closers: dict[str, Callable[[], None]] = {}


def _now() -> float:
    """Horloge monotone du rattachement (isolée pour rester mockable)."""
    return time.monotonic()


def new_terminal(
    family: Family, target: str, owner: str, session: str | None = None
) -> LiveTerminal:
    """Fabrique un LiveTerminal avec id stable (uuid4) et `since` horodaté.

    Réservé aux appelants « live » (handlers websocket) — le code testé de
    façon déterministe construit `LiveTerminal` directement.
    """
    return LiveTerminal(
        id=uuid.uuid4().hex,
        family=family,
        target=target,
        owner=owner,
        session=session,
        since=_now(),
    )


def register(term: LiveTerminal, closer: Callable[[], None] | None = None) -> None:
    """Enregistre (ou remplace) un terminal vivant. Idempotent par id.

    `closer` (optionnel) est le callback invoqué par `close_matching` pour
    fermer le pont à distance ; absent → le terminal n'est pas fermable via API
    (il ne se ferme qu'en coupant le websocket côté client).
    """
    _terminals[term.id] = term
    if closer is not None:
        _closers[term.id] = closer


def unregister(id: str) -> None:
    """Retire un terminal et son closer. Silencieux si l'id est inconnu."""
    _terminals.pop(id, None)
    _closers.pop(id, None)
    _evicted.discard(id)


def evict_others(term: LiveTerminal) -> int:
    """Ferme les autres terminaux du même propriétaire sur la même session.

    Un seul écran à la fois. Deux clients tmux sur une même session font caler
    la fenêtre sur le dernier actif (`window-size latest`) : l'autre écran
    reçoit alors des cellules calculées pour une géométrie qui n'est pas la
    sienne — curseur mal placé, texte entrelacé, et aucune cause visible pour
    l'utilisateur (diagnostiqué le 03/09 après trois fausses pistes).

    Le nouveau venu prend la main ; les précédents sont fermés avec un motif,
    ce qui permet au navigateur de proposer « reconnecter » — et cette
    reconnexion évincera à son tour celui qui aura pris la place.

    Renvoie le nombre de terminaux évincés.
    """
    count = 0
    for autre in list(_terminals.values()):
        if autre.id == term.id:
            continue
        if (autre.family, autre.target, autre.session, autre.owner) != (
            term.family,
            term.target,
            term.session,
            term.owner,
        ):
            continue
        closer = _closers.pop(autre.id, None)
        if closer is None:
            continue
        _evicted.add(autre.id)
        closer()
        count += 1
    return count


def was_evicted(id: str) -> bool:
    """Ce terminal a-t-il été fermé au profit d'un autre appareil ?"""
    return id in _evicted


def close_matching(*, family: Family, target: str, session: str | None, owner: str | None) -> int:
    """Ferme les terminaux vivants correspondant à (family, target, session).

    `owner=None` → toutes les instances (vue admin) ; sinon restreint au login
    donné (garde-fou : un user ne ferme que ses propres terminaux). Invoque le
    closer de chaque terminal correspondant (le téardown effectif — kill process,
    fermeture websocket, `unregister` — a lieu dans le handler du websocket).
    Renvoie le nombre de closers invoqués.
    """
    count = 0
    for term in list(_terminals.values()):
        if term.family != family or term.target != target or term.session != session:
            continue
        if owner is not None and term.owner != owner:
            continue
        closer = _closers.pop(term.id, None)
        if closer is not None:
            closer()
            count += 1
    return count


def list_all() -> list[LiveTerminal]:
    return list(_terminals.values())


def list_for_owner(login: str) -> list[LiveTerminal]:
    return [t for t in _terminals.values() if t.owner == login]


def attached_index(*, owner: str | None) -> set[AttachKey]:
    """Ensemble des clés (family, target, session) attachées.

    `owner=None` → toutes les instances (vue admin) ; sinon restreint au login.
    Une clé présente dans l'ensemble signale une session actuellement attachée.
    """
    terms = list_all() if owner is None else list_for_owner(owner)
    return {(t.family, t.target, t.session) for t in terms}


def count_attached(*, family: Family, target: str, session: str | None, owner: str) -> int:
    """Nombre de terminaux vivants sur cette session, pour ce propriétaire.

    Sert à prévenir l'utilisateur qu'il regarde la même session tmux depuis deux
    appareils : tmux cale alors la fenêtre sur le client le plus récemment actif
    (`window-size latest`), et l'écran le plus petit reçoit des lignes trop
    longues — affichage déformé sans cause visible.

    Ne compte que les terminaux de CETTE instance du portail : un client attaché
    par un autre chemin (ssh direct, autre instance) reste invisible.
    """
    return sum(
        1
        for t in _terminals.values()
        if t.family == family and t.target == target and t.session == session and t.owner == owner
    )


def clear() -> None:
    """Tests uniquement : vide le registre entre deux cas."""
    _terminals.clear()
    _closers.clear()
    _evicted.clear()
