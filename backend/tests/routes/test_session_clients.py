"""Compte des terminaux attachés à une session (enabler « signaler le partage »).

Deux appareils sur la même session tmux, c'est tmux qui cale la fenêtre sur le
client le plus récemment actif : l'écran le plus petit reçoit des lignes trop
longues et se retrouve déformé, sans que rien ne l'explique.
"""

from __future__ import annotations

import pytest

from portal.sessions import registry


@pytest.fixture(autouse=True)
def _registre_vierge() -> None:
    registry.clear()
    yield
    registry.clear()


def _attacher(*, owner: str, target: str, session: str | None) -> None:
    registry.register(
        registry.new_terminal(family="workspace", target=target, owner=owner, session=session)
    )


def test_compte_zero_sans_terminal() -> None:
    assert (
        registry.count_attached(
            family="workspace", target="admin-rag", session="rag1", owner="admin"
        )
        == 0
    )


def test_compte_les_terminaux_de_la_meme_session() -> None:
    # Le cas qui motive tout : le PC et le mobile sur la même session.
    _attacher(owner="admin", target="admin-rag", session="rag1")
    _attacher(owner="admin", target="admin-rag", session="rag1")

    assert (
        registry.count_attached(
            family="workspace", target="admin-rag", session="rag1", owner="admin"
        )
        == 2
    )


def test_ne_compte_pas_une_autre_session() -> None:
    _attacher(owner="admin", target="admin-rag", session="rag2")

    assert (
        registry.count_attached(
            family="workspace", target="admin-rag", session="rag1", owner="admin"
        )
        == 0
    )


def test_ne_compte_pas_un_autre_workspace() -> None:
    _attacher(owner="admin", target="admin-devpod", session="rag1")

    assert (
        registry.count_attached(
            family="workspace", target="admin-rag", session="rag1", owner="admin"
        )
        == 0
    )


def test_ne_compte_pas_un_autre_proprietaire() -> None:
    # Isolation : le compte d'un utilisateur ne doit rien révéler d'un autre.
    _attacher(owner="autre", target="admin-rag", session="rag1")

    assert (
        registry.count_attached(
            family="workspace", target="admin-rag", session="rag1", owner="admin"
        )
        == 0
    )


def test_ne_compte_pas_une_autre_famille() -> None:
    registry.register(
        registry.new_terminal(family="host", target="admin-rag", owner="admin", session="rag1")
    )

    assert (
        registry.count_attached(
            family="workspace", target="admin-rag", session="rag1", owner="admin"
        )
        == 0
    )


def test_le_detachement_fait_baisser_le_compte() -> None:
    term = registry.new_terminal(
        family="workspace", target="admin-rag", owner="admin", session="rag1"
    )
    registry.register(term)
    registry.unregister(term.id)

    assert (
        registry.count_attached(
            family="workspace", target="admin-rag", session="rag1", owner="admin"
        )
        == 0
    )
