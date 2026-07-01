"""Canal d'exécution non-interactif sur un nœud enrôlé (host type=ssh).

Seul point d'exécution des commandes compose (cadrage spec 26). Mirroir de
ssh_exec.run_ssh_capture mais ciblant host.address (pas un workspace devpod).
"""
from __future__ import annotations

import asyncio
import base64
import posixpath
import shlex
from collections.abc import AsyncIterator
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
        if host.usage == "tests":
            raise HostExecError(
                f"La machine de test {host.name!r} n'a pas SSH activé. "
                "Supprimez-la et recréez-la via le bouton « Add VM for Test » "
                "pour relancer l'enrôlement SSH."
            )
        missing = []
        if not host.address:
            missing.append("adresse SSH")
        if not host.host_cert_slug:
            missing.append("certificat SSH (host_cert_slug)")
        raise HostExecError(
            f"La machine {host.name!r} n'a pas SSH activé ({', '.join(missing)} manquant(s)). "
            "Activez SSH sur cette machine depuis le panneau d'administration des hôtes."
        )


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


def _check_host_key_changed(host: HostConfig, err: str) -> None:
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in err:
        raise HostExecError(
            f"La clé SSH de la machine {host.name!r} ({host.address}) a changé "
            "(réinstallation probable). Détruisez la machine de test et recréez-la "
            "depuis l'onglet Test pour résoudre le problème."
        )


async def run_host_command(
    host: HostConfig, command: str, *, timeout: float = 120.0
) -> tuple[int, str, str]:
    _require_ssh_host(host)
    known = _data_root() / "keys" / "hosts_known"
    await asyncio.to_thread(known.parent.mkdir, parents=True, exist_ok=True)
    key_path = await _materialize_system_cert(host.host_cert_slug)
    argv = _argv(key_path, host.address, command, known)
    rc, out, err = await _ssh_capture(argv, timeout=timeout)
    _check_host_key_changed(host, err)
    return rc, out, err


async def stream_host_command(
    host: HostConfig, command: str, *, timeout: float = 600.0
) -> AsyncIterator[str]:
    """Exécute une commande SSH en streaming (stdout+stderr mergés), yield une ligne à la fois."""
    _require_ssh_host(host)
    known = _data_root() / "keys" / "hosts_known"
    await asyncio.to_thread(known.parent.mkdir, parents=True, exist_ok=True)
    key_path = await _materialize_system_cert(host.host_cert_slug)
    argv = _argv(key_path, host.address, command, known)

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None  # stdout=PIPE garantit un StreamReader

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            remaining = max(1.0, deadline - loop.time())
            if loop.time() >= deadline:
                raise HostExecError("commande nœud expirée (timeout)")
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except TimeoutError:
                raise HostExecError("commande nœud expirée (timeout)") from None
            if not raw:
                break
            yield raw.decode("utf-8", errors="replace").rstrip("\n")
    except HostExecError:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise

    await proc.wait()
    if proc.returncode != 0:
        raise HostExecError(f"commande SSH échouée (rc={proc.returncode})")


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
