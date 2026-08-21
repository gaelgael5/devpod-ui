from __future__ import annotations

import asyncio
import contextlib
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, WebSocket

from ..auth.rbac import session_within_max_age
from ..config.store import _data_root, load_global
from ..devpod.exec import remote_tmux_command
from ..devpod.service import _materialize_system_cert
from ..devpod.ssh_exec import host_key_changed
from ..sessions import registry
from ..sessions.pty_bridge import requested_size, run_pty_bridge
from ..settings import get_settings

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["ssh-proxy"])

_SESSION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}$")


@router.websocket("/hosts/{name}/ssh")
async def host_ssh_terminal(
    name: str,
    websocket: WebSocket,
    session: str = "main",
    cols: int | None = None,
    rows: int | None = None,
) -> None:
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
    if not session_within_max_age(websocket.session):
        # Plafond d'âge absolu (bug 032) : session expirée → re-login requis.
        await websocket.close(code=4001, reason="Session expired")
        return
    if settings.oidc_admin_role not in user_data.get("roles", []):
        _log.warning("ws_ssh_admin_denied", login=user_data.get("login"))
        await websocket.close(code=4001, reason="Admin role required")
        return

    # ── Config ────────────────────────────────────────────────────────────────
    if not _SESSION_NAME_RE.fullmatch(session):
        await websocket.close(code=4022, reason="Invalid session name")
        return
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

    # Terminal dans tmux (session persistante, réattachable) ; PTY local pour que
    # le resize se propage (SIGWINCH) — les trames texte sont du contrôle, pas du stdin.
    cmd = [
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
        remote_tmux_command(session),
    ]

    # Enregistrement du terminal vivant (vue centralisée des sessions).
    live_term = registry.new_terminal(
        family="host", target=name, owner=user_data.get("login") or "admin", session=session
    )

    returncode = await run_pty_bridge(
        websocket,
        cmd,
        # Le portail n'a pas de terminal : forcer un TERM propagé par ssh -t -t.
        {**os.environ, "TERM": "xterm-256color"},
        live_term,
        log_label="ws_ssh",
        initial_size=requested_size(cols, rows),
    )

    if tmp_key_path.startswith(tempfile.gettempdir()):
        with contextlib.suppress(OSError):
            Path(tmp_key_path).unlink()

    _log.info("ws_ssh_closed", host=name, returncode=returncode)
