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
from ..recipes.registry import RecipeRegistry
from ..settings import get_settings

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["workspace-ssh"])

_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")


@router.websocket("/workspaces/{name}/ssh")
async def workspace_ssh_terminal(
    name: str,
    websocket: WebSocket,
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
            _log.warning("ws_workspace_ssh_bad_origin", origin=request_origin, allowed=allowed_origin)
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

    # ── Résolution de la start recipe (si fournie) ────────────────────────────
    tmux_cmd: str
    if start is not None:
        from ..recipes.models import _RECIPE_ID_RE

        if not _RECIPE_ID_RE.fullmatch(start):
            await websocket.close(code=4022, reason=f"Invalid start recipe id {start!r}")
            return

        data_root = _data_root()
        shared_dir = data_root / "recipes"
        personal_dir = safe_user_path(login, "recipes")
        registry = RecipeRegistry(builtin_dir=None, shared_dir=shared_dir)
        shared = registry.load_shared()
        personal = registry.load_dir(personal_dir)
        available = {**shared, **personal}

        recipe = available.get(start)
        if recipe is None or recipe.type != "start":
            await websocket.close(code=4022, reason=f"Start recipe {start!r} not found")
            return

        # Localiser le répertoire de la recette (personal a priorité)
        if (personal_dir / start).exists():
            recipe_dir = personal_dir / start
        else:
            recipe_dir = shared_dir / start
        start_sh_path = recipe_dir / "start.sh"
        if not start_sh_path.exists():
            await websocket.close(code=4022, reason=f"start.sh missing for {start!r}")
            return

        script_content = start_sh_path.read_text(encoding="utf-8")
        b64 = base64.b64encode(script_content.encode()).decode()
        tmux_cmd = f"tmux new -A -s {start} -- bash -lc \"$(echo {b64} | base64 -d)\""
    else:
        tmux_cmd = "tmux new -A -s main"

    # ── Build commande devpod ssh ─────────────────────────────────────────────
    devpod_bin = shlex.split(cfg.devpod.binary, posix=(os.name != "nt"))
    cmd = [*devpod_bin, "ssh", ws_id, "--command", tmux_cmd]

    _log.info("ws_workspace_ssh_open", ws_id=ws_id, login=login, start=start)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
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
