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


@pytest.fixture
async def child():
    proc, master_fd = await spawn_on_pty(["python3", "-c", _CHILD], dict(os.environ))
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
