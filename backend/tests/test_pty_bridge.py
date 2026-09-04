"""Le pont applique-t-il vraiment les trames de contrôle au PTY ?

Le trou couvert ici : les redimensionnements envoyés par le navigateur étaient
journalisés côté front, jamais appliqués côté PTY, et les deux `suppress` du
pont rendaient l'échec indétectable.
"""

from __future__ import annotations

import asyncio
import contextlib
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
    """Websocket minimal : débite les trames fournies puis se déconnecte.

    `garder_ouvert` retient la déconnexion. Le nudge est asynchrone : un pont
    qui se démonte aussitôt ses trames lues l'annulerait avant son terme, et le
    test ne mesurerait rien.
    """

    def __init__(self, frames: list[dict], *, garder_ouvert: bool = False) -> None:
        self._frames = [*frames] if garder_ouvert else [*frames, {"type": "websocket.disconnect"}]
        self.sent: list[bytes] = []

    async def receive(self) -> dict:
        if self._frames:
            return self._frames.pop(0)
        await asyncio.sleep(3600)  # plus rien à lire : on ne rend jamais la main
        raise AssertionError("inatteignable")

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        # Enregistre le motif : le pont doit fermer avec un code parlant quand
        # la session est reprise sur un autre appareil.
        self.closed: tuple[int, str] = (code, reason)


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


def _trame(**champs) -> dict:
    return {"type": "websocket.receive", "text": json.dumps({"type": "resize", **champs})}


async def _pont_vivant(frames: list[dict], *, duree: float) -> None:
    """Fait tourner le pont `duree` secondes sur des trames données, puis coupe.

    Le pont doit RESTER en vie : c'est pendant qu'il vit que la seconde moitié
    du nudge s'applique.
    """
    ws = _FakeWebSocket(frames, garder_ouvert=True)
    tache = asyncio.create_task(
        run_pty_bridge(
            ws,  # type: ignore[arg-type]
            ["sleep", "5"],
            {"TERM": "xterm", "PATH": "/usr/bin:/bin"},
            _FakeTerminal(),  # type: ignore[arg-type]
            log_label="test",
            # Aucune taille d'amorcage : ces tests portent sur les trames de
            # controle, et une taille initiale ajouterait un appel parasite au
            # journal de l'espion.
            initial_size=None,
        )
    )
    await asyncio.sleep(duree)
    tache.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tache


@pytest.mark.asyncio
async def test_le_nudge_applique_la_taille_reduite_puis_la_vraie(monkeypatch):
    """Deux SIGWINCH, pas un seul : c'est ce qui fait repeindre tmux."""
    monkeypatch.setattr("portal.sessions.pty_bridge.NUDGE_DELAY_S", 0.01)
    vues: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "portal.sessions.pty_bridge.set_pty_size",
        lambda _fd, cols, rows: vues.append((cols, rows)),
    )

    await _pont_vivant([_trame(cols=265, rows=65, nudge=True)], duree=0.06)

    assert vues == [(265, 64), (265, 65)]


@pytest.mark.asyncio
async def test_le_nudge_espace_reellement_les_deux_tailles(monkeypatch):
    """Le coeur de la correction : sans écart, tmux ne voit qu'un changement.

    Mesuré en production le 03/09/2026, les deux trames du navigateur
    arrivaient dans la même milliseconde. Le délai ne peut pas être tenu là-bas
    — deux trames émises à une frame d'écart sont livrées dans le même segment
    TCP — il l'est donc ici, où l'horloge est celle du poseur d'ioctl.
    """
    monkeypatch.setattr("portal.sessions.pty_bridge.NUDGE_DELAY_S", 0.05)
    instants: list[float] = []
    monkeypatch.setattr(
        "portal.sessions.pty_bridge.set_pty_size",
        lambda *_a: instants.append(asyncio.get_running_loop().time()),
    )

    await _pont_vivant([_trame(cols=265, rows=65, nudge=True)], duree=0.2)

    assert len(instants) == 2
    assert instants[1] - instants[0] >= 0.04


@pytest.mark.asyncio
async def test_un_resize_vers_une_autre_taille_annule_le_nudge(monkeypatch):
    """La fenêtre a rebougé pendant le nudge : c'est la NOUVELLE taille qui vaut.

    Sans annulation, le nudge poserait sa taille périmée après coup et laisserait
    le PTY sur une géométrie que plus personne n'a demandée.
    """
    monkeypatch.setattr("portal.sessions.pty_bridge.NUDGE_DELAY_S", 0.05)
    vues: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "portal.sessions.pty_bridge.set_pty_size",
        lambda _fd, cols, rows: vues.append((cols, rows)),
    )

    await _pont_vivant(
        [_trame(cols=265, rows=65, nudge=True), _trame(cols=100, rows=40)],
        duree=0.2,
    )

    assert vues == [(265, 64), (100, 40)]


@pytest.mark.asyncio
async def test_un_resize_vers_la_meme_taille_laisse_le_nudge_finir(monkeypatch):
    """`onResize` d'xterm émet sa propre trame juste avant celle du nudge.

    Les deux visent la même taille finale. Si la première annulait la seconde —
    ou l'inverse — l'ordre d'arrivée déciderait du repaint, ce qui est exactement
    le genre de dépendance au réseau qu'on cherche à supprimer.
    """
    monkeypatch.setattr("portal.sessions.pty_bridge.NUDGE_DELAY_S", 0.05)
    vues: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "portal.sessions.pty_bridge.set_pty_size",
        lambda _fd, cols, rows: vues.append((cols, rows)),
    )

    await _pont_vivant(
        [_trame(cols=265, rows=65, nudge=True), _trame(cols=265, rows=65)],
        duree=0.2,
    )

    assert vues == [(265, 64), (265, 65)]


@pytest.mark.asyncio
async def test_le_nudge_ne_descend_pas_a_zero_ligne(monkeypatch):
    """Un terminal d'une ligne existe ; un terminal de zéro ligne, non."""
    monkeypatch.setattr("portal.sessions.pty_bridge.NUDGE_DELAY_S", 0.01)
    vues: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "portal.sessions.pty_bridge.set_pty_size",
        lambda _fd, cols, rows: vues.append((cols, rows)),
    )

    await _pont_vivant([_trame(cols=80, rows=1, nudge=True)], duree=0.06)

    assert vues == [(80, 1)]


@pytest.mark.asyncio
async def test_le_nudge_est_annule_a_la_fermeture_du_pont(monkeypatch):
    """Sinon il pose une taille sur un descripteur déjà fermé, pour rien.

    Le `finally` du pont ferme le maître : une tâche survivante journaliserait
    un `pty_set_size_failed` (EBADF) sans rapport avec un vrai incident.
    """
    monkeypatch.setattr("portal.sessions.pty_bridge.NUDGE_DELAY_S", 0.5)
    vues: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "portal.sessions.pty_bridge.set_pty_size",
        lambda _fd, cols, rows: vues.append((cols, rows)),
    )

    # Le pont est coupé bien avant la fin du délai.
    await _pont_vivant([_trame(cols=265, rows=65, nudge=True)], duree=0.05)
    await asyncio.sleep(0.6)

    assert vues == [(265, 64)]


@pytest.mark.asyncio
async def test_le_nudge_journalise_ses_deux_moities(monkeypatch):
    """Sans les deux lignes, l'espacement réel des SIGWINCH est invérifiable.

    C'est la seule mesure qui permette de calibrer `NUDGE_DELAY_S` sur des logs
    de production — et de voir un nudge inopérant AVANT que l'utilisateur ne
    voie l'écran cassé.
    """
    monkeypatch.setattr("portal.sessions.pty_bridge.NUDGE_DELAY_S", 0.01)
    monkeypatch.setattr("portal.sessions.pty_bridge.set_pty_size", lambda *_a: None)
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

    await _pont_vivant([_trame(cols=265, rows=65, nudge=True, octets=0)], duree=0.06)

    nudges = [kw for evt, kw in infos if evt == "test_resize_applied"]
    assert nudges == [
        {"cols": 265, "rows": 64, "nudge": "debut", "octets": 0},
        {"cols": 265, "rows": 65, "nudge": "fin", "octets": 0},
    ]


@pytest.mark.asyncio
async def test_une_trame_absorbee_par_le_nudge_laisse_une_trace(monkeypatch):
    """L'invariant de `_handle_control` : aucune sortie sans effet n'est muette.

    Sans cette ligne, « la trame n'arrive pas » et « la trame est absorbée par
    un nudge en vol » sont indiscernables au diagnostic — le défaut que ce
    handler dit précisément avoir corrigé.
    """
    monkeypatch.setattr("portal.sessions.pty_bridge.NUDGE_DELAY_S", 0.05)
    monkeypatch.setattr("portal.sessions.pty_bridge.set_pty_size", lambda *_a: None)
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

    await _pont_vivant(
        [_trame(cols=265, rows=65, nudge=True), _trame(cols=265, rows=65)],
        duree=0.2,
    )

    absorbees = [kw for evt, kw in infos if evt == "test_resize_absorbed_by_nudge"]
    assert absorbees == [{"cols": 265, "rows": 65}]
