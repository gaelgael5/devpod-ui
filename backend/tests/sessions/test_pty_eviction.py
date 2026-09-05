"""Un seul écran à la fois : le nouveau venu reprend la main.

Deux clients tmux sur une même session font caler la fenêtre sur le dernier
actif (`window-size latest`) : l'autre écran reçoit alors des cellules
calculées pour une géométrie qui n'est pas la sienne — curseur mal placé,
texte entrelacé, aucune cause visible pour l'utilisateur.
"""

from __future__ import annotations

import asyncio

import pytest

from portal.sessions import registry
from portal.sessions.pty_bridge import run_pty_bridge
from portal.sessions.registry import LiveTerminal


@pytest.fixture(autouse=True)
def _registre_propre():
    registry.clear()
    yield
    registry.clear()


class _WebSocketMuet:
    """Ne débite aucune trame : le pont ne rend la main que si on le ferme."""

    def __init__(self) -> None:
        self.closed: tuple[int, str] | None = None

    async def receive(self) -> dict:
        await asyncio.sleep(3600)
        raise AssertionError("inatteignable")

    async def send_bytes(self, data: bytes) -> None:
        return None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)


def _terminal(id: str) -> LiveTerminal:
    return LiveTerminal(
        id=id, family="workspace", target="alice-ws", owner="alice", session="main", since=1.0
    )


@pytest.mark.asyncio
async def test_le_second_ecran_evince_le_premier_avec_un_code_parlant() -> None:
    ws = _WebSocketMuet()
    premier = _terminal("premier")
    pont = asyncio.create_task(
        run_pty_bridge(
            ws,  # type: ignore[arg-type]
            ["sleep", "30"],
            {"TERM": "xterm", "PATH": "/usr/bin:/bin"},
            premier,  # type: ignore[arg-type]
            log_label="test",
            initial_size=(80, 24),
        )
    )
    # Laisse le pont s'enregistrer avant d'ouvrir le second écran.
    for _ in range(50):
        await asyncio.sleep(0)
        if any(t.id == "premier" for t in registry.list_all()):
            break
    assert any(t.id == "premier" for t in registry.list_all())

    # Le second écran arrive : il prend la main.
    second = _terminal("second")
    registry.register(second, closer=lambda: None)
    assert registry.evict_others(second) == 1

    await asyncio.wait_for(pont, timeout=5)

    # 4409 : le navigateur distingue « repris ailleurs » d'une coupure réseau.
    assert ws.closed == (4409, "Session reprise sur un autre appareil")
    # Le premier a bien quitté le registre ; le second garde la main.
    assert [t.id for t in registry.list_all()] == ["second"]


@pytest.mark.asyncio
async def test_une_fermeture_ordinaire_garde_le_code_par_defaut() -> None:
    """Sans éviction, rien ne change : pas de faux signal côté navigateur."""
    ws = _WebSocketMuet()
    seul = _terminal("seul")
    pont = asyncio.create_task(
        run_pty_bridge(
            ws,  # type: ignore[arg-type]
            ["sleep", "30"],
            {"TERM": "xterm", "PATH": "/usr/bin:/bin"},
            seul,  # type: ignore[arg-type]
            log_label="test",
            initial_size=(80, 24),
        )
    )
    for _ in range(50):
        await asyncio.sleep(0)
        if any(t.id == "seul" for t in registry.list_all()):
            break

    registry.close_matching(family="workspace", target="alice-ws", session="main", owner="alice")
    await asyncio.wait_for(pont, timeout=5)

    assert ws.closed == (1000, "")
