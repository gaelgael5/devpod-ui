from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import re
import shlex
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..config.store import _data_root, load_global, safe_user_path
from ..db.engine import _get_engine
from ..db.recipes import load_recipes_as_dict
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
    if session is not None:
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

        data_root = _data_root()
        shared_dir = data_root / "recipes"
        personal_dir = safe_user_path(login, "recipes")
        async with _get_engine().connect() as _conn:
            available = await load_recipes_as_dict(login, _conn, type_filter="start")
        recipe = available.get(start)
        if recipe is None:
            await websocket.close(code=4022, reason=f"Start recipe {start!r} not found")
            return

        # Localiser le répertoire de la recette (personal a priorité)
        if (personal_dir / start).exists():
            recipe_dir = personal_dir / start
            if not recipe_dir.is_relative_to(personal_dir):
                await websocket.close(code=4022, reason="Path traversal detected")
                return
        else:
            recipe_dir = shared_dir / start
            if not recipe_dir.is_relative_to(shared_dir):
                await websocket.close(code=4022, reason="Path traversal detected")
                return
        start_sh_path = recipe_dir / "start.sh"
        if not start_sh_path.exists():
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
    cmd = [
        "ssh", "-t", "-t",
        "-o", f"ProxyCommand={proxy_cmd}",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "--", "root@devpod-ws",
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

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=devpod_env,
    )

    async def _ws_to_ssh() -> None:
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                raw: bytes | None = message.get("bytes")
                if raw is None:
                    raw = (message.get("text") or "").encode()
                if raw and proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.write(raw)
                    await proc.stdin.drain()
        except (WebSocketDisconnect, OSError):
            pass
        except Exception as exc:
            _log.warning("ws_workspace_ssh_ws_to_ssh_error", exc_type=type(exc).__name__)

    async def _ssh_to_ws() -> None:
        try:
            if proc.stdout is None:
                return
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                await websocket.send_bytes(chunk)
        except (WebSocketDisconnect, OSError):
            pass
        except Exception as exc:
            _log.warning("ws_workspace_ssh_ssh_to_ws_error", exc_type=type(exc).__name__)

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
        with contextlib.suppress(Exception):
            await websocket.close()

    _log.info("ws_workspace_ssh_closed", ws_id=ws_id, returncode=proc.returncode)
