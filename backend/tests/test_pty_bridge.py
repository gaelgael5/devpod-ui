"""Le pont applique-t-il vraiment les trames de contrôle au PTY ?

Le trou couvert ici : les redimensionnements envoyés par le navigateur étaient
journalisés côté front, jamais appliqués côté PTY, et les deux `suppress` du
pont rendaient l'échec indétectable.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import struct
import termios

import pytest

from portal.sessions.pty_bridge import run_pty_bridge, set_pty_size


def _taille(fd: int) -> tuple[int, int]:
    """(cols, rows) lues sur le PTY."""
    rows, cols = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))[:2]
    return cols, rows


class _FakeWebSocket:
    """Websocket minimal : débite les trames fournies puis se déconnecte."""

    def __init__(self, frames: list[dict]) -> None:
        self._frames = [*frames, {"type": "websocket.disconnect"}]
        self.sent: list[bytes] = []

    async def receive(self) -> dict:
        if self._frames:
            return self._frames.pop(0)
        await asyncio.sleep(3600)  # plus rien à lire : on ne rend jamais la main
        raise AssertionError("inatteignable")

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        return None


class _FakeTerminal:
    id = "term-test"


@pytest.fixture(autouse=True)
def _registre_neutre(monkeypatch):
    """Le registre des terminaux vivants n'est pas le sujet de ce test."""
    from portal.sessions import registry

    monkeypatch.setattr(registry, "register", lambda *a, **k: None)
    monkeypatch.setattr(registry, "unregister", lambda *a, **k: None)


@pytest.mark.asyncio
async def test_trame_resize_appliquee_au_pty(monkeypatch):
    vues: list[tuple[int, int]] = []

    def _espion(fd: int, cols: int, rows: int) -> None:
        vues.append((cols, rows))
        set_pty_size(fd, cols, rows)

    monkeypatch.setattr("portal.sessions.pty_bridge.set_pty_size", _espion)

    ws = _FakeWebSocket(
        [
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "resize", "cols": 104, "rows": 63}),
            },
        ]
    )
    await run_pty_bridge(
        ws,  # type: ignore[arg-type]
        ["sleep", "5"],
        {"TERM": "xterm", "PATH": "/usr/bin:/bin"},
        _FakeTerminal(),  # type: ignore[arg-type]
        log_label="test",
        initial_size=(234, 64),
    )

    # La taille d'ouverture, puis celle demandée par la trame.
    assert vues == [(234, 64), (104, 63)]


@pytest.mark.asyncio
async def test_trame_de_controle_illisible_nignore_pas_le_reste(monkeypatch):
    """Une trame invalide ne doit ni lever, ni tuer le pont, ni rester muette."""
    avertissements: list[str] = []
    monkeypatch.setattr(
        "portal.sessions.pty_bridge._log",
        type(
            "L",
            (),
            {
                "warning": lambda _self, evt, **kw: avertissements.append(evt),
                "info": lambda _self, evt, **kw: None,
            },
        )(),
    )

    ws = _FakeWebSocket(
        [
            {"type": "websocket.receive", "text": "{pas du json"},
            {"type": "websocket.receive", "text": json.dumps({"type": "autre"})},
        ]
    )
    await run_pty_bridge(
        ws,  # type: ignore[arg-type]
        ["sleep", "5"],
        {"TERM": "xterm", "PATH": "/usr/bin:/bin"},
        _FakeTerminal(),  # type: ignore[arg-type]
        log_label="test",
        initial_size=(80, 24),
    )

    assert avertissements == ["test_control_invalid_json", "test_control_unknown"]


def test_set_pty_size_journalise_un_descripteur_invalide(monkeypatch):
    """L'échec d'ioctl était avalé : plus aucune trace d'un PTY non redimensionné."""
    avertissements: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "portal.sessions.pty_bridge._log",
        type("L", (), {"warning": lambda _self, evt, **kw: avertissements.append((evt, kw))})(),
    )

    # Descripteur refermé = EBADF : le cas réel, quand le pont est démonté
    # pendant qu'une trame de redimensionnement est encore en vol.
    maitre, esclave = pty.openpty()
    os.close(maitre)
    os.close(esclave)
    set_pty_size(maitre, 100, 40)

    assert avertissements[0][0] == "pty_set_size_failed"
    assert avertissements[0][1]["cols"] == 100


@pytest.mark.asyncio
async def test_sonde_client_journalisee_avec_le_resize(monkeypatch):
    """La sonde voyage sur la trame `resize`, jamais sur une trame a elle.

    Une trame de controle supplementaire fermait la session a chaque ouverture
    du clavier mobile (03/09). Les champs sont donc optionnels et embarques :
    un client plus ancien ne les envoie pas, le pont journalise sans eux.
    """
    infos: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "portal.sessions.pty_bridge._log",
        type(
            "L",
            (),
            {
                "warning": lambda _self, evt, **kw: None,
                "info": lambda _self, evt, **kw: infos.append((evt, kw)),
            },
        )(),
    )
    monkeypatch.setattr("portal.sessions.pty_bridge.set_pty_size", lambda *a: None)

    ws = _FakeWebSocket(
        [
            {
                "type": "websocket.receive",
                "text": json.dumps(
                    {"type": "resize", "cols": 54, "rows": 28, "haut": 900, "vv": 420, "octets": 17}
                ),
            },
            # Client sans la sonde : la trame reste valide, on journalise sans.
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "resize", "cols": 54, "rows": 49}),
            },
        ]
    )
    await run_pty_bridge(
        ws,  # type: ignore[arg-type]
        ["sleep", "5"],
        {"TERM": "xterm", "PATH": "/usr/bin:/bin"},
        _FakeTerminal(),  # type: ignore[arg-type]
        log_label="test",
        initial_size=(80, 24),
    )

    appliques = [kw for evt, kw in infos if evt == "test_resize_applied"]
    assert appliques == [
        {"cols": 54, "rows": 28, "haut": 900, "vv": 420, "octets": 17},
        {"cols": 54, "rows": 49},
    ]
