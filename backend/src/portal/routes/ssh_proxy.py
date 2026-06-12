from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..config.store import _data_root, load_global
from ..settings import get_settings

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["ssh-proxy"])


@router.websocket("/hosts/{name}/ssh")
async def host_ssh_terminal(name: str, websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    cfg = load_global()

    # ── Origin validation (anti-CSWSH) ────────────────────────────────────────
    if not settings.dev_mode:
        parsed = urlparse(cfg.server.external_url)
        allowed_origin = f"{parsed.scheme}://{parsed.netloc}"
        request_origin = websocket.headers.get("origin", "").rstrip("/")
        if request_origin != allowed_origin:
            _log.warning("ws_ssh_bad_origin", origin=request_origin)
            await websocket.close(code=4003, reason="Bad origin")
            return

    # ── Auth ──────────────────────────────────────────────────────────────────
    user_data = websocket.session.get("user")
    if not user_data or not isinstance(user_data, dict):
        await websocket.close(code=4001, reason="Not authenticated")
        return
    if settings.oidc_admin_role not in user_data.get("roles", []):
        _log.warning("ws_ssh_admin_denied", login=user_data.get("login"))
        await websocket.close(code=4001, reason="Admin role required")
        return

    # ── Config ────────────────────────────────────────────────────────────────
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        await websocket.close(code=4004, reason=f"Host {name!r} not found")
        return
    if host.type != "ssh":
        await websocket.close(code=4022, reason=f"Host {name!r} is not of type ssh")
        return
    if not host.key_path:
        await websocket.close(code=4022, reason="key_path not configured for this host")
        return

    # ── Sécurité key_path ─────────────────────────────────────────────────────
    key_path = Path(host.key_path).resolve()
    data_root = _data_root().resolve()
    if not key_path.is_relative_to(data_root):
        _log.warning("ws_ssh_key_path_traversal", key_path=str(key_path))
        await websocket.close(code=4022, reason="key_path must be under data root")
        return
    if not key_path.exists():
        await websocket.close(code=4022, reason=f"key_path does not exist: {host.key_path}")
        return

    # ── Proxy SSH ─────────────────────────────────────────────────────────────
    address = host.address
    _log.info("ws_ssh_open", host=name, address=address, admin=user_data.get("login"))

    known_hosts = _data_root() / "keys" / "hosts_known"
    known_hosts.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "ssh",
        "-i", str(key_path),
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-o", "BatchMode=no",
        address,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async def _ws_to_ssh() -> None:
        try:
            while True:
                data = await websocket.receive_bytes()
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.write(data)
                    await proc.stdin.drain()
        except (WebSocketDisconnect, OSError):
            pass
        except Exception as exc:
            _log.warning("ws_ssh_ws_to_ssh_error", exc_type=type(exc).__name__)

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
            _log.warning("ws_ssh_ssh_to_ws_error", exc_type=type(exc).__name__)

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

    _log.info("ws_ssh_closed", host=name, returncode=proc.returncode)
