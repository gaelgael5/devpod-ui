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


def clear() -> None:
    """Tests uniquement : vide le registre entre deux cas."""
    _terminals.clear()
    _closers.clear()
