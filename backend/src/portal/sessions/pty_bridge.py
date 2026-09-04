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

# Écart entre les deux tailles d'un « nudge » (cf. `run_pty_bridge`).
#
# SIGWINCH n'est pas un signal temps réel : le noyau ne le met pas en file. Un
# second changement de taille appliqué avant que l'application n'ait traité le
# premier se fond dedans — un seul réveil, et l'application lit alors la taille
# FINALE. Pour un aller-retour `rows-1` → `rows`, cela revient à ne rien avoir
# changé du tout : tmux ne redessine pas, et l'écran reste faux.
#
# Ce délai ne peut pas être tenu par le navigateur : ses deux trames, émises à
# une frame d'écart, sont livrées dans le même segment TCP. Mesuré en production
# le 03/09/2026, elles arrivaient au pont dans la MÊME milliseconde.
#
# Valeur calibrée sur des logs réels : à 80 ms, l'écart était bien tenu (mesuré
# à 81 ms côté PTY) mais tmux ne repeignait TOUJOURS pas — résidus en colonne 0
# encore visibles à l'écran le 04/09. Un tmux occupé à dessiner a une fenêtre de
# coalescence plus large qu'un processus oisif : le second SIGWINCH tombait
# encore pendant qu'il traitait le premier. Remonté à 160 ms, palier suivant du
# plan de calibration.
NUDGE_DELAY_S = 0.16


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
    # et l'intérêt est de savoir SI les trames arrivent, pas de les compter
    # toutes. 40 et non 20 : un nudge consomme désormais DEUX lignes (début et
    # fin — c'est la paire qui rend l'espacement des SIGWINCH mesurable dans
    # les logs), et une session mobile en mange une paire par cycle de clavier.
    controls = 0

    # Nudge en vol, et la taille qu'il finira par poser. Le client demande un
    # repaint (`nudge: true`) ; l'aller-retour de taille est exécuté ICI, parce
    # que les deux SIGWINCH doivent être espacés d'un délai réel (cf.
    # `NUDGE_DELAY_S`) et que le navigateur ne peut pas le garantir.
    nudge: asyncio.Task[None] | None = None
    nudge_cible: tuple[int, int] | None = None

    def _annuler_nudge() -> None:
        nonlocal nudge, nudge_cible
        if nudge is not None and not nudge.done():
            nudge.cancel()
        nudge, nudge_cible = None, None

    def _journal_borne(evenement: str, **champs: object) -> None:
        nonlocal controls
        if controls >= 40:
            return
        controls += 1
        _log.info(f"{log_label}_{evenement}", **champs)

    async def _nudge_puis_vraie_taille(cols: int, rows: int, sonde: dict[str, int]) -> None:
        """Seconde moitié du nudge : la vraie taille, une fois le premier signal reçu."""
        nonlocal nudge_cible
        await asyncio.sleep(NUDGE_DELAY_S)
        _pty_resize(cols, rows)
        # Relâché AVANT la journalisation : une trame ultérieure visant cette
        # même taille doit repouvoir déclencher un nudge, sinon un écran ne se
        # repeindrait plus jamais à géométrie constante.
        nudge_cible = None
        _journal_borne("resize_applied", cols=cols, rows=rows, nudge="fin", **sonde)

    def _handle_control(payload: str) -> None:
        """Traite une trame texte (message de contrôle). Aucun échec silencieux.

        Chaque sortie sans effet se journalise : c'est le seul moyen de
        distinguer « la trame n'arrive pas » de « la trame arrive et n'est pas
        appliquée » — les deux étaient indiscernables tant que tout le bloc
        était sous `suppress(Exception)`.
        """
        nonlocal nudge, nudge_cible
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
        # Sonde client embarquee sur la trame, jamais sur une trame a elle :
        # une trame de controle supplementaire fermait la session a chaque
        # ouverture du clavier mobile (03/09). Champs absents = client plus
        # ancien, ou mesure pas encore prise.
        sonde = {cle: msg[cle] for cle in ("haut", "vv", "octets") if isinstance(msg.get(cle), int)}

        if nudge_cible is not None:
            # Même taille finale : c'est la trame que `onResize` d'xterm émet
            # juste avant celle du nudge. La laisser annuler le nudge ferait
            # dependre le repaint de l'ordre d'arrivée des deux — precisement la
            # dependance au reseau qu'on supprime. Absorbée mais pas muette
            # (l'invariant du docstring) : sans trace, « la trame n'arrive pas »
            # et « la trame est absorbée » sont indiscernables au diagnostic.
            if (cols, rows) == nudge_cible:
                _journal_borne("resize_absorbed_by_nudge", cols=cols, rows=rows)
                return
            # La fenetre a rebouge : la nouvelle taille prime, et le nudge ne
            # doit pas poser la sienne, perimee, apres coup.
            _annuler_nudge()

        # Un terminal d'une ligne existe, un terminal de zero ligne non : sous
        # `rows == 1`, il n'y a pas de taille intermediaire a poser.
        if msg.get("nudge") is True and rows > 1:
            _pty_resize(cols, rows - 1)
            # Journalisée aussi : c'est l'écart entre cette ligne et sa jumelle
            # `nudge="fin"` qui rend l'espacement réel des SIGWINCH mesurable —
            # et donc NUDGE_DELAY_S calibrable sur des logs de production.
            _journal_borne("resize_applied", cols=cols, rows=rows - 1, nudge="debut", **sonde)
            nudge_cible = (cols, rows)
            nudge = asyncio.create_task(_nudge_puis_vraie_taille(cols, rows, sonde))
            return

        _pty_resize(cols, rows)
        _journal_borne("resize_applied", cols=cols, rows=rows, **sonde)

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
    # Un seul ecran a la fois. Deux clients tmux sur une meme session font caler
    # la fenetre sur le dernier actif : l'autre recoit des cellules calculees
    # pour une geometrie qui n'est pas la sienne. Le nouveau venu prend la main.
    evinces = registry.evict_others(live_term)
    if evinces:
        _log.info(f"{log_label}_evicted_others", count=evinces)
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Lu AVANT `unregister`, qui efface le motif.
        evince = registry.was_evicted(live_term.id)
        registry.unregister(live_term.id)
        # Avant la fermeture du maître : un nudge survivant poserait une taille
        # sur un descripteur fermé et journaliserait un EBADF sans incident réel.
        _annuler_nudge()
        for t in tasks:
            t.cancel()
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        with contextlib.suppress(OSError):
            os.close(master_fd)
        with contextlib.suppress(Exception):
            # 4409 : le navigateur distingue « repris ailleurs » d'une coupure
            # reseau, et propose de reprendre la main plutot qu'un message muet.
            if evince:
                await websocket.close(code=4409, reason="Session reprise sur un autre appareil")
            else:
                await websocket.close()

    return proc.returncode
