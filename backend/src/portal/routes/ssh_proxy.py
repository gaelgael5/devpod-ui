from __future__ import annotations

import asyncio
import contextlib
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..config.store import _data_root, load_global
from ..devpod.service import _materialize_system_cert
from ..devpod.ssh_exec import host_key_changed
from ..settings import get_settings

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["ssh-proxy"])


@router.websocket("/hosts/{name}/ssh")
async def host_ssh_terminal(name: str, websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    cfg = load_global()

    _log.info("ws_ssh_handler_entry", host=name, dev_mode=settings.dev_mode)

    # ── Origin validation (anti-CSWSH) ────────────────────────────────────────
    if not settings.dev_mode:
        parsed = urlparse(cfg.server.external_url)
        allowed_origin = f"{parsed.scheme}://{parsed.netloc}"
        request_origin = websocket.headers.get("origin", "").rstrip("/")
        if request_origin != allowed_origin:
            _log.warning("ws_ssh_bad_origin", origin=request_origin, allowed=allowed_origin)
            await websocket.close(code=4003, reason="Bad origin")
            return

    # ── Auth ──────────────────────────────────────────────────────────────────
    user_data = websocket.session.get("user")
    if not user_data or not isinstance(user_data, dict):
        _log.warning(
            "ws_ssh_unauthenticated",
            host=name,
            session_is_empty=not bool(websocket.session),
            session_keys=list(websocket.session.keys()),
        )
        await websocket.close(code=4001, reason="Not authenticated")
        return
    if settings.oidc_admin_role not in user_data.get("roles", []):
        _log.warning("ws_ssh_admin_denied", login=user_data.get("login"))
        await websocket.close(code=4001, reason="Admin role required")
        return

    # ── Config ────────────────────────────────────────────────────────────────
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        _log.warning("ws_ssh_host_not_found", host=name, known=[h.name for h in cfg.hosts])
        await websocket.close(code=4004, reason=f"Host {name!r} not found")
        return
    if host.type != "ssh":
        _log.warning("ws_ssh_not_ssh_type", host=name, host_type=host.type)
        await websocket.close(code=4022, reason=f"Host {name!r} is not of type ssh")
        return
    if not host.host_cert_slug:
        _log.warning("ws_ssh_empty_host_cert_slug", host=name)
        await websocket.close(code=4022, reason="host_cert_slug not configured for this host")
        return

    # ── Matérialisation de la clé SSH depuis harpo ────────────────────────────
    try:
        tmp_key_path = await _materialize_system_cert(host.host_cert_slug)
    except KeyError:
        _log.warning("ws_ssh_cert_not_found", host=name, slug=host.host_cert_slug)
        await websocket.close(code=4022, reason=f"SSH cert not found: {host.host_cert_slug}")
        return
    except Exception:
        _log.error("ws_ssh_cert_materialize_failed", host=name, exc_info=True)
        await websocket.close(code=4022, reason="Failed to retrieve SSH key")
        return

    # ── Proxy SSH ─────────────────────────────────────────────────────────────
    address = host.address
    _log.info("ws_ssh_open", host=name, address=address, admin=user_data.get("login"))

    known_hosts = _data_root() / "keys" / "hosts_known"
    known_hosts.parent.mkdir(parents=True, exist_ok=True)

    # Nœud potentiellement recréé (clé d'hôte changée, fréquent avec DHCP) : pré-test
    # non-interactif. On purge l'ancienne entrée UNIQUEMENT sur un vrai changement de
    # clé → la vérification reste active pour les hôtes stables (pas de re-trust aveugle).
    hostname = address.split("@", 1)[-1]
    precheck = await asyncio.create_subprocess_exec(
        "ssh",
        "-i",
        tmp_key_path,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "ConnectTimeout=10",
        address,
        "true",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, precheck_err = await precheck.communicate()
    if host_key_changed(precheck_err):
        _log.warning("ws_ssh_host_key_changed_purge", host=name, hostname=hostname)
        purge = await asyncio.create_subprocess_exec(
            "ssh-keygen",
            "-f",
            str(known_hosts),
            "-R",
            hostname,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await purge.wait()

    proc = await asyncio.create_subprocess_exec(
        "ssh",
        "-t",
        "-t",  # force PTY même quand stdin est un pipe
        "-i",
        tmp_key_path,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "BatchMode=no",
        address,
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
        if tmp_key_path.startswith(tempfile.gettempdir()):
            with contextlib.suppress(OSError):
                Path(tmp_key_path).unlink()

    _log.info("ws_ssh_closed", host=name, returncode=proc.returncode)
