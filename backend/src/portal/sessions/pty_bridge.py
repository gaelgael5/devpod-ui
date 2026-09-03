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


def requested_size(cols: int | None, rows: int | None) -> tuple[int, int] | None:
    """Taille demandée par le client, bornée. `None` si non fournie.

    Bornes hautes : la valeur vient du navigateur et finit dans un `ioctl`.
    """
    if not cols or not rows:
        return None
    return (max(1, min(cols, 1000)), max(1, min(rows, 1000)))


def set_pty_size(fd: int, cols: int, rows: int) -> None:
    """Applique la taille au PTY maître. Un échec est journalisé, jamais avalé.

    Le `suppress(OSError)` d'origine rendait la panne muette : mesuré le
    02/09/2026, trois redimensionnements envoyés par le navigateur (149, 104
    puis 234 colonnes) laissaient le PTY distant figé sur sa taille d'ouverture,
    sans une ligne de log nulle part. tmux dessinait alors des lignes plus
    larges que le terminal, qui se repliaient en escalier sur le bord gauche.
    """
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError as exc:
        _log.warning("pty_set_size_failed", cols=cols, rows=rows, errno=exc.errno)


async def spawn_on_pty(
    cmd: list[str],
    env: dict[str, str],
    size: tuple[int, int] | None = None,
) -> tuple[asyncio.subprocess.Process, int]:
    """Lance `cmd` sur un PTY neuf dont il est le terminal de contrôle.

    `size` (cols, rows) est posée AVANT l'exec : `ssh` lit la taille de son
    terminal au démarrage pour dimensionner le PTY distant, et ne la relit
    jamais. Fournie trop tard, elle ne rattrape plus tmux, qui s'est déjà calé
    sur les 80x24 par défaut d'OpenSSH.

    Retourne le process et le descripteur maître (au vidage de l'appelant).
    """
    master_fd, slave_fd = pty.openpty()
    if size:
        set_pty_size(master_fd, *size)
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
    initial_size: tuple[int, int] | None = None,
) -> int | None:
    """Lance `cmd` sur un PTY et fait le pont avec `websocket` jusqu'à fermeture.

    Retourne le returncode du subprocess (None s'il a fallu le tuer sans code).
    """
    proc, master_fd = await spawn_on_pty(cmd, env, initial_size)

    def _pty_resize(cols: int, rows: int) -> None:
        set_pty_size(master_fd, cols, rows)

    # Bornée comme les autres sondes : un glissé de fenêtre produit une rafale,
    # et l'intérêt est de savoir SI les trames arrivent, pas de les compter toutes.
    controls = 0

    def _handle_control(payload: str) -> None:
        """Traite une trame texte (message de contrôle). Aucun échec silencieux.

        Chaque sortie sans effet se journalise : c'est le seul moyen de
        distinguer « la trame n'arrive pas » de « la trame arrive et n'est pas
        appliquée » — les deux étaient indiscernables tant que tout le bloc
        était sous `suppress(Exception)`.
        """
        nonlocal controls
        try:
            msg = json.loads(payload)
        except ValueError:
            _log.warning(f"{log_label}_control_invalid_json", size=len(payload))
            return
        if not isinstance(msg, dict) or msg.get("type") != "resize":
            _log.warning(f"{log_label}_control_unknown", payload=payload[:120])
            return
        try:
            cols = max(1, int(msg.get("cols", 80)))
            rows = max(1, int(msg.get("rows", 24)))
        except (TypeError, ValueError):
            _log.warning(f"{log_label}_control_bad_size", payload=payload[:120])
            return
        _pty_resize(cols, rows)
        if controls < 20:
            controls += 1
            # Sonde client embarquee sur la trame, jamais sur une trame a elle :
            # une trame de controle supplementaire fermait la session a chaque
            # ouverture du clavier mobile (03/09). Champs absents = client plus
            # ancien, ou mesure pas encore prise.
            sonde = {
                cle: msg[cle] for cle in ("haut", "vv", "octets") if isinstance(msg.get(cle), int)
            }
            _log.info(f"{log_label}_resize_applied", cols=cols, rows=rows, **sonde)

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
                    _handle_control(text)
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
