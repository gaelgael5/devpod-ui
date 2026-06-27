"""Canal d'exécution non-interactif sur un nœud enrôlé (host type=ssh).

Seul point d'exécution des commandes compose (cadrage spec 26). Mirroir de
ssh_exec.run_ssh_capture mais ciblant host.address (pas un workspace devpod).
"""
from __future__ import annotations

import asyncio
import base64
import posixpath
import shlex
from pathlib import Path

import structlog

from ..config.models import HostConfig
from ..config.store import _data_root
from .service import _materialize_system_cert

_log = structlog.get_logger(__name__)


class HostExecError(Exception):
    """Échec d'exécution sur un nœud (FR)."""


def _require_ssh_host(host: HostConfig) -> None:
    if host.type != "ssh":
        raise HostExecError(f"host {host.name!r} n'est pas de type ssh (v1 ssh-only)")
    if not host.address or not host.host_cert_slug:
        raise HostExecError(f"host {host.name!r} : address/host_cert_slug non configurés")


def _argv(key_path: str, address: str, command: str, known_hosts: Path) -> list[str]:
    return [
        "ssh", "-i", key_path,
        "-o", "BatchMode=yes",
        "-o", "LogLevel=ERROR",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-o", "ConnectTimeout=15",
        address, command,
    ]


async def _ssh_capture(argv: list[str], *, timeout: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        _log.warning("host_exec_timeout", address=argv[-2] if len(argv) >= 2 else "unknown")
        raise HostExecError("commande nœud expirée (timeout)") from None
    rc = proc.returncode if proc.returncode is not None else -1
    return rc, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")


async def run_host_command(
    host: HostConfig, command: str, *, timeout: float = 120.0
) -> tuple[int, str, str]:
    _require_ssh_host(host)
    known = _data_root() / "keys" / "hosts_known"
    await asyncio.to_thread(known.parent.mkdir, parents=True, exist_ok=True)
    key_path = await _materialize_system_cert(host.host_cert_slug)
    argv = _argv(key_path, host.address, command, known)
    return await _ssh_capture(argv, timeout=timeout)


async def write_host_file(host: HostConfig, remote_path: str, content: str) -> None:
    if "\0" in remote_path:
        raise HostExecError("chemin distant invalide")
    if remote_path.startswith("~"):
        raise HostExecError(
            "chemin distant ~ non supporté (shlex.quote casse l'expansion); "
            "utilisez un chemin relatif"
        )
    parent = posixpath.dirname(remote_path)
    b64 = base64.b64encode(content.encode()).decode()
    cmd = (
        f"mkdir -p {shlex.quote(parent)} && "
        f"printf %s {shlex.quote(b64)} | base64 -d > {shlex.quote(remote_path)}"
    )
    rc, _, err = await run_host_command(host, cmd)
    if rc != 0:
        raise HostExecError(f"écriture distante échouée ({remote_path}): {err}")
