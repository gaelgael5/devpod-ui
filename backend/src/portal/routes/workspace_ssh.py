from __future__ import annotations

import asyncio
import base64
import contextlib
import fcntl
import json
import os
import pty
import re
import shlex
import struct
import termios
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..config.store import load_global, safe_user_path
from ..db.engine import _get_engine
from ..db.recipes import load_recipes_as_dict
from ..devpod.ssh_exec import devpod_ssh_key as _devpod_ssh_key
from ..settings import get_settings

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["workspace-ssh"])

_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_SESSION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}$")


@router.websocket("/workspaces/{name}/ssh")
async def workspace_ssh_terminal(
    name: str,
    websocket: WebSocket,
    session: str | None = None,
    start: str | None = None,
    shell: bool = False,
) -> None:
    await websocket.accept()
    settings = get_settings()
    cfg = load_global()

    # ── Origin validation (anti-CSWSH) ────────────────────────────────────────
    if not settings.dev_mode:
        parsed = urlparse(cfg.server.external_url)
        allowed_origin = f"{parsed.scheme}://{parsed.netloc}"
        request_origin = websocket.headers.get("origin", "").rstrip("/")
        if request_origin != allowed_origin:
            _log.warning(
                "ws_workspace_ssh_bad_origin",
                origin=request_origin,
                allowed=allowed_origin,
            )
            await websocket.close(code=4003, reason="Bad origin")
            return

    # ── Auth ──────────────────────────────────────────────────────────────────
    user_data = websocket.session.get("user")
    if not user_data or not isinstance(user_data, dict):
        _log.warning(
            "ws_workspace_ssh_unauthenticated",
            workspace=name,
            session_is_empty=not bool(websocket.session),
            session_keys=list(websocket.session.keys()),
        )
        await websocket.close(code=4001, reason="Not authenticated")
        return
    login: str = user_data.get("login", "")
    if not login:
        await websocket.close(code=4001, reason="Invalid session")
        return

    # ── Validation du nom de workspace ────────────────────────────────────────
    if not _WS_NAME_RE.fullmatch(name):
        await websocket.close(code=4022, reason="Invalid workspace name")
        return

    ws_id = f"{login}-{name}"

    # ── Résolution de la commande tmux ───────────────────────────────────────
    # Le serveur tmux tourne en uid 1000 (vscode) ; root peut accéder à son
    # socket Unix car root bypasse les DAC.  On détecte le socket actif dans
    # /tmp/tmux-*/ et on passe -S $SOCK à tmux — pas besoin de su.
    _sock = (
        "TMUX_SOCK=$(find /tmp -maxdepth 2 -name default"
        " -path '*/tmux-*/*' 2>/dev/null | head -1)"
    )
    _tmux = 'TERM=xterm-256color tmux ${TMUX_SOCK:+-S "$TMUX_SOCK"}'

    tmux_cmd: str
    if shell:
        # Mode shell brut : bash interactif sans tmux — utile pour le debug.
        tmux_cmd = "exec bash -l"
    elif session is not None:
        if not _SESSION_NAME_RE.fullmatch(session):
            await websocket.close(code=4022, reason="Invalid session name")
            return
        # new-session -A : attache si la session existe, crée sinon.
        tmux_cmd = f"{_sock}; {_tmux} new-session -A -s {shlex.quote(session)}"
    elif start is not None:
        from ..recipes.models import _RECIPE_ID_RE

        if not _RECIPE_ID_RE.fullmatch(start):
            await websocket.close(code=4022, reason=f"Invalid start recipe id {start!r}")
            return

        async with _get_engine().connect() as _conn:
            available = await load_recipes_as_dict(login, _conn, type_filter="start")
        if start not in available:
            await websocket.close(code=4022, reason=f"Start recipe {start!r} not found")
            return

        # Fallback bundlé inclus (start validé par _RECIPE_ID_RE → pas de traversal).
        from .workspace_sessions import locate_start_sh

        start_sh_path = locate_start_sh(login, start)
        if start_sh_path is None:
            await websocket.close(code=4022, reason=f"start.sh missing for {start!r}")
            return

        script_content = start_sh_path.read_text(encoding="utf-8")
        b64 = base64.b64encode(script_content.encode()).decode()
        run_script = f'bash -lc "$(echo {b64} | base64 -d)"'
        has_tmux = "command -v tmux >/dev/null 2>&1"
        tmux_cmd = (
            f"{has_tmux} && {_sock}; {_tmux} new -A -s {start} -- {run_script}"
            f" || {run_script}"
        )
    else:
        tmux_cmd = f"{_sock}; {_tmux} new -A -s main || bash -l"

    # ── Build commande SSH ────────────────────────────────────────────────────
    # ProxyCommand explicite : n'utilise plus ~/.ssh/config (perdu au rebuild).
    # -t -t force l'allocation PTY même quand stdin est un pipe.
    if ws_id.startswith("-"):
        await websocket.close(code=4022, reason="Invalid workspace SSH host")
        return
    devpod_bin = cfg.devpod.binary
    proxy_cmd = f"{shlex.quote(devpod_bin)} ssh --stdio {shlex.quote(ws_id)}"
    key_path = _devpod_ssh_key(login)
    identity_args = (
        ["-i", key_path, "-o", "IdentitiesOnly=yes"] if key_path else []
    )
    cmd = [
        "ssh", "-t", "-t",
        *identity_args,
        "-o", f"ProxyCommand={proxy_cmd}",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "--", "vscode@devpod-ws",
        tmux_cmd,
    ]

    # DEVPOD_HOME → devpod ssh --stdio trouve la config workspace.
    devpod_env = {
        **dict(os.environ),
        "DEVPOD_HOME": str(safe_user_path(login, "devpod")),
        "HOME": os.environ.get("HOME", "/root"),
        # SSH propage TERM local vers le PTY remote avec -t -t.
        # Le processus portal n'a pas de vrai terminal → forcer xterm-256color.
        "TERM": "xterm-256color",
    }

    _log.info("ws_workspace_ssh_open", ws_id=ws_id, login=login, start=start)

    # PTY local : SSH reçoit un vrai terminal → SIGWINCH propagé correctement.
    # Avec stdin=PIPE, SSH ne peut pas détecter les changements de taille et
    # tmux reste à 80 colonnes même si la fenêtre du navigateur est plus large.
    master_fd, slave_fd = pty.openpty()  # type: ignore[attr-defined]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=devpod_env,
        )
    finally:
        os.close(slave_fd)  # le parent n'a besoin que du master

    def _pty_resize(cols: int, rows: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.ioctl(  # type: ignore[attr-defined]
                master_fd,
                termios.TIOCSWINSZ,  # type: ignore[attr-defined]
                struct.pack("HHHH", rows, cols, 0, 0),
            )

    async def _ws_to_ssh() -> None:
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
            _log.warning("ws_workspace_ssh_ws_to_ssh_error", exc_type=type(exc).__name__)

    async def _ssh_to_ws() -> None:
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
            _log.warning("ws_workspace_ssh_ssh_to_ws_error", exc_type=type(exc).__name__)
        finally:
            loop.remove_reader(master_fd)

    tasks = [
        asyncio.create_task(_ws_to_ssh()),
        asyncio.create_task(_ssh_to_ws()),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        with contextlib.suppress(OSError):
            os.close(master_fd)
        with contextlib.suppress(Exception):
            await websocket.close()

    _log.info("ws_workspace_ssh_closed", ws_id=ws_id, returncode=proc.returncode)
