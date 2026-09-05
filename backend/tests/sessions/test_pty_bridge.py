"""Terminal de contrôle du PTY des sessions SSH.

Le défaut corrigé ici : le process lancé sur le PTY n'en était pas le leader de
session. `TIOCSWINSZ` mettait bien la taille à jour, mais le `SIGWINCH` qui doit
suivre est adressé au groupe de processus au premier plan du terminal — inexistant
dans ce cas. `ssh` gardait la taille lue au démarrage et tmux dessinait à 80
colonnes quel que soit le navigateur.

Ces tests exercent le vrai mécanisme noyau : un enfant réel, un vrai PTY, un vrai
signal. Un double mocké ne prouverait rien ici, puisque c'est précisément la
délivrance du signal qui était en cause.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import struct
import termios

import pytest

from portal.sessions.pty_bridge import spawn_on_pty

# Rapporte sa taille de terminal à chaque SIGWINCH, jusqu'à ce qu'on le tue.
_CHILD = """
import fcntl, os, signal, struct, sys, termios

def report(*_):
    rows, cols, _x, _y = struct.unpack('HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ, b'\\0' * 8))
    sys.stdout.write('WINCH %dx%d\\n' % (cols, rows))
    sys.stdout.flush()

signal.signal(signal.SIGWINCH, report)
sys.stdout.write('READY\\n')
sys.stdout.flush()
while True:
    signal.pause()
"""


# Meme rapport, mais l'enfant est OCCUPE au demarrage : il bloque SIGWINCH le
# temps de sa "frame de dessin". C'est l'etat de tmux en train de repeindre —
# et le seul moyen deterministe de reproduire la coalescence, qui depend sinon
# de l'ordonnanceur.
_CHILD_OCCUPE = """
import fcntl, signal, struct, sys, termios, time

def report(*_):
    rows, cols, _x, _y = struct.unpack('HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ, b'\\0' * 8))
    sys.stdout.write('WINCH %dx%d\\n' % (cols, rows))
    sys.stdout.flush()

signal.signal(signal.SIGWINCH, report)
signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGWINCH})
sys.stdout.write('OCCUPE\\n')
sys.stdout.flush()
time.sleep(0.3)
signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGWINCH})
while True:
    signal.pause()
"""


def _set_size(master_fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


async def _read_line(master_fd: int, timeout: float = 5.0) -> str:
    """Lit une ligne sur le maître, sans bloquer la boucle asyncio."""
    loop = asyncio.get_running_loop()
    buf = b""
    async with asyncio.timeout(timeout):
        while not buf.endswith(b"\n"):
            buf += await loop.run_in_executor(None, os.read, master_fd, 1)
    return buf.decode(errors="replace").strip()


# Rapporte une seule fois la taille de son terminal, puis sort.
_REPORT_ONCE = """
import fcntl, struct, sys, termios
rows, cols, _x, _y = struct.unpack('HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ, b'\\0' * 8))
sys.stdout.write('SIZE %dx%d\\n' % (cols, rows))
sys.stdout.flush()
"""


async def _size_reported_by_child(size: tuple[int, int] | None) -> str:
    """Lance un enfant qui annonce la taille lue au demarrage, puis nettoie."""
    proc, master_fd = await spawn_on_pty(
        ["python3", "-c", _REPORT_ONCE], dict(os.environ), size=size
    )
    try:
        return await _read_line(master_fd)
    finally:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        os.close(master_fd)


@pytest.fixture
async def child():
    proc, master_fd = await spawn_on_pty(["python3", "-c", _CHILD], dict(os.environ))
    try:
        yield proc, master_fd
    finally:
        proc.kill()
        await proc.wait()
        os.close(master_fd)


@pytest.fixture
async def child_occupe():
    proc, master_fd = await spawn_on_pty(["python3", "-c", _CHILD_OCCUPE], dict(os.environ))
    try:
        yield proc, master_fd
    finally:
        proc.kill()
        await proc.wait()
        os.close(master_fd)


async def test_le_pty_est_le_terminal_de_controle_de_l_enfant(child):
    """Sans groupe au premier plan, aucun SIGWINCH n'est delivrable."""
    proc, master_fd = child
    assert await _read_line(master_fd) == "READY"

    # tcgetpgrp echoue (ENOTTY) si le PTY n'a pas de session attachee.
    assert os.tcgetpgrp(master_fd) == proc.pid


async def test_le_redimensionnement_atteint_le_process(child):
    proc, master_fd = child
    assert await _read_line(master_fd) == "READY"

    _set_size(master_fd, 100, 30)

    assert await _read_line(master_fd) == "WINCH 100x30"


async def test_les_redimensionnements_successifs_sont_tous_recus(child):
    """Clavier qui s'ouvre, rotation : la taille change plusieurs fois de suite."""
    proc, master_fd = child
    assert await _read_line(master_fd) == "READY"

    for cols, rows in ((56, 20), (56, 12), (120, 40)):
        _set_size(master_fd, cols, rows)
        assert await _read_line(master_fd) == f"WINCH {cols}x{rows}"


async def test_deux_redimensionnements_colles_ne_font_voir_aucun_changement(child_occupe):
    """La cause racine du nudge qui ne repeint pas.

    SIGWINCH n'est pas un signal temps reel : il n'est pas mis en file. Un
    second signal arrive alors que le premier est encore pendant ne s'ajoute
    pas — il se fond dedans. L'application n'est reveillee qu'une fois, et lit
    alors la taille FINALE.

    Pour le nudge, c'est fatal : `rows-1` puis `rows` colles ne font voir a tmux
    qu'un seul changement, vers la taille qu'il avait deja. Rien n'a bouge de
    son point de vue, il ne redessine pas — et l'ecran casse le reste.

    Mesure en production le 03/09/2026 : les deux trames du nudge arrivaient au
    pont dans la MEME milliseconde.
    """
    _proc, master_fd = child_occupe
    assert await _read_line(master_fd) == "OCCUPE"

    # L'enfant tient son masque : les deux tailles sont posees pendant qu'il
    # "dessine", exactement comme tmux qui n'a pas encore traite le premier.
    _set_size(master_fd, 100, 29)
    _set_size(master_fd, 100, 30)

    assert await _read_line(master_fd) == "WINCH 100x30"
    # Et c'est tout : le signal du 29 n'a jamais ete delivre separement.
    with pytest.raises(TimeoutError):
        await _read_line(master_fd, timeout=0.5)


async def test_espaces_du_delai_du_pont_les_deux_signaux_sont_delivres(child):
    """La correction : c'est l'espacement qui rend le nudge operant.

    Le delai ne peut pas etre tenu par le navigateur — ses deux trames partent
    a une frame d'ecart et arrivent dans le meme segment TCP. Il l'est donc par
    le pont, dont l'horloge est celle du processus qui pose l'ioctl.

    Ce test etablit le mecanisme, PAS la marge : l'enfant est ici oisif et
    traite son signal aussitot, alors que tmux occupe a dessiner a une fenetre
    de coalescence bien plus large. Le dimensionnement de NUDGE_DELAY_S se fait
    sur les logs reels.
    """
    from portal.sessions.pty_bridge import NUDGE_DELAY_S

    _proc, master_fd = child
    assert await _read_line(master_fd) == "READY"
    _set_size(master_fd, 100, 30)
    assert await _read_line(master_fd) == "WINCH 100x30"

    _set_size(master_fd, 100, 29)
    await asyncio.sleep(NUDGE_DELAY_S)
    _set_size(master_fd, 100, 30)

    # Deux reveils distincts : tmux voit sa fenetre changer, puis rechanger.
    assert await _read_line(master_fd) == "WINCH 100x29"
    assert await _read_line(master_fd) == "WINCH 100x30"


async def test_la_taille_initiale_est_posee_avant_l_exec():
    """`ssh` lit la taille de son terminal au demarrage et ne la relit jamais.

    Fournie apres l'exec, elle ne rattrape plus le PTY distant : tmux reste cale
    sur les 80x24 par defaut d'OpenSSH pour toute la session.
    """
    assert await _size_reported_by_child(size=(56, 20)) == "SIZE 56x20"


async def test_sans_taille_le_pty_reste_a_zero():
    """Contraste : c'est cette taille nulle qui fait basculer ssh sur 80x24."""
    assert await _size_reported_by_child(size=None) == "SIZE 0x0"


@pytest.mark.parametrize(
    ("cols", "rows", "attendu"),
    [
        (56, 20, (56, 20)),
        (None, 20, None),
        (56, None, None),
        (0, 0, None),
        (99999, 99999, (1000, 1000)),  # borne : la valeur vient du navigateur
    ],
)
def test_taille_demandee_bornee(cols, rows, attendu):
    from portal.sessions.pty_bridge import requested_size

    assert requested_size(cols, rows) == attendu
