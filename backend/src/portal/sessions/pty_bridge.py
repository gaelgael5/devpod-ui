"""Pont websocket ↔ subprocess sur PTY local, partagé par tous les terminaux SSH.

Mutualise le pont des terminaux workspace, host admin et VM de test :
- PTY local → SSH voit un vrai terminal, SIGWINCH propagé (tmux se redimensionne) ;
- trame texte = message de contrôle JSON (`{"type":"resize",cols,rows}`) ;
- trame binaire = stdin brut ;
- enregistrement dans le registre des terminaux vivants (closer = annulation du
  pont, invoqué par `POST /sessions/close`) ; teardown symétrique quel que soit
  le côté qui ferme (kill du process, close du websocket, unregister).
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

import structlog
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from . import registry

_log = structlog.get_logger(__name__)


def _attach_controlling_tty() -> None:
    """Fait de l'enfant un leader de session et du PTY son terminal de contrôle.

    Sans cela le PTY n'a aucun groupe de processus au premier plan. `TIOCSWINSZ`
    met bien à jour la taille, mais le `SIGWINCH` qui doit suivre est adressé à
    ce groupe — donc à personne. `ssh` conserve alors la taille lue au démarrage
    et tmux dessine à une largeur qui n'est pas celle du navigateur.

    Exécuté entre `fork` et `exec` : stdin est déjà le côté esclave du PTY. Les
    échecs sont absorbés — mal dimensionnée, la session reste utilisable ; morte,
    non. On ne journalise pas ici : après `fork`, y compris dans l'interpréteur,
    seules les opérations async-signal-safe sont sûres.
    """
    with contextlib.suppress(OSError):
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)


async def spawn_on_pty(
    cmd: list[str], env: dict[str, str]
) -> tuple[asyncio.subprocess.Process, int]:
    """Lance `cmd` sur un PTY neuf dont il est le terminal de contrôle.

    Retourne le process et le descripteur maître (au vidage de l'appelant).
    """
    master_fd, slave_fd = pty.openpty()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            preexec_fn=_attach_controlling_tty,
        )
    finally:
        os.close(slave_fd)  # le parent n'a besoin que du maître
    return proc, master_fd


async def run_pty_bridge(
    websocket: WebSocket,
    cmd: list[str],
    env: dict[str, str],
    live_term: registry.LiveTerminal,
    *,
    log_label: str,
) -> int | None:
    """Lance `cmd` sur un PTY et fait le pont avec `websocket` jusqu'à fermeture.

    Retourne le returncode du subprocess (None s'il a fallu le tuer sans code).
    """
    proc, master_fd = await spawn_on_pty(cmd, env)

    def _pty_resize(cols: int, rows: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.ioctl(
                master_fd,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", rows, cols, 0, 0),
            )

    async def _ws_to_pty() -> None:
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                text: str | None = message.get("text")
                raw: bytes | None = message.get("bytes")
                if text:
                    # Trame texte = message de contrôle (resize)
                    with contextlib.suppress(Exception):
                        msg = json.loads(text)
                        if msg.get("type") == "resize":
                            _pty_resize(
                                max(1, int(msg.get("cols", 80))),
                                max(1, int(msg.get("rows", 24))),
                            )
                elif raw:
                    with contextlib.suppress(OSError):
                        os.write(master_fd, raw)
        except (WebSocketDisconnect, OSError):
            pass
        except Exception as exc:
            _log.warning(f"{log_label}_ws_to_ssh_error", exc_type=type(exc).__name__)

    async def _pty_to_ws() -> None:
        loop = asyncio.get_event_loop()
        q: asyncio.Queue[bytes | None] = asyncio.Queue()

        def _on_readable() -> None:
            try:
                data = os.read(master_fd, 4096)
                q.put_nowait(data or None)
            except OSError:
                q.put_nowait(None)
                loop.remove_reader(master_fd)

        loop.add_reader(master_fd, _on_readable)
        try:
            while True:
                chunk = await q.get()
                if chunk is None:
                    break
                await websocket.send_bytes(chunk)
        except (WebSocketDisconnect, OSError):
            pass
        except Exception as exc:
            _log.warning(f"{log_label}_ssh_to_ws_error", exc_type=type(exc).__name__)
        finally:
            loop.remove_reader(master_fd)

    tasks = [
        asyncio.create_task(_ws_to_pty()),
        asyncio.create_task(_pty_to_ws()),
    ]

    # Closer : `POST /sessions/close` annule le pont ; le `finally` ci-dessous
    # tue alors le process et ferme le websocket (téardown identique à une
    # déconnexion navigateur).
    def _closer() -> None:
        for t in tasks:
            t.cancel()

    registry.register(live_term, closer=_closer)
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        registry.unregister(live_term.id)
        for t in tasks:
            t.cancel()
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        with contextlib.suppress(OSError):
            os.close(master_fd)
        with contextlib.suppress(Exception):
            await websocket.close()

    return proc.returncode
