"""Exécution SSH non-interactive dans un workspace (capture stdout/stderr).

Complète `routes/workspace_ssh.py` (terminal interactif via PTY) : ici on lance une
commande courte et on capture sa sortie — utilisé par les actions `initialize`.
"""

from __future__ import annotations

import asyncio
import os
import shlex

import structlog

from ..config.store import load_global, safe_user_path

_log = structlog.get_logger(__name__)


def host_key_changed(ssh_stderr: bytes) -> bool:
    """True si la sortie SSH signale un changement de clé d'hôte (nœud recréé).

    Distinct d'un hôte simplement inconnu (à accepter via accept-new) : on ne purge
    le known_hosts que sur un vrai changement, pour préserver la vérification.
    """
    text = ssh_stderr.decode("utf-8", errors="replace")
    return "REMOTE HOST IDENTIFICATION HAS CHANGED" in text


def devpod_ssh_key(login: str) -> str | None:
    """Clé privée SSH générée par devpod pour cet utilisateur (ou None)."""
    ssh_dir = safe_user_path(login, "devpod") / "ssh"
    if not ssh_dir.exists():
        return None
    for name in ("id_rsa", "id_ed25519", "id_devpod"):
        key = ssh_dir / name
        if key.exists():
            return str(key)
    for f in sorted(ssh_dir.iterdir()):
        if f.is_file() and f.suffix != ".pub":
            return str(f)
    return None


def build_ssh_argv(
    ws_id: str, remote_cmd: str, *, devpod_bin: str, key_path: str | None
) -> list[str]:
    """Construit l'argv ssh avec ProxyCommand devpod (sans PTY)."""
    if ws_id.startswith("-"):
        raise ValueError(f"invalid workspace SSH host: {ws_id!r}")
    proxy_cmd = f"{shlex.quote(devpod_bin)} ssh --stdio {shlex.quote(ws_id)}"
    identity_args = ["-i", key_path, "-o", "IdentitiesOnly=yes"] if key_path else []
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "LogLevel=ERROR",
        *identity_args,
        "-o",
        f"ProxyCommand={proxy_cmd}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "--",
        "vscode@devpod-ws",
        remote_cmd,
    ]


def ssh_env(login: str) -> dict[str, str]:
    """Environnement pour `devpod ssh --stdio` (DEVPOD_HOME + HOME)."""
    return {
        **dict(os.environ),
        "DEVPOD_HOME": str(safe_user_path(login, "devpod")),
        "HOME": os.environ.get("HOME", "/root"),
    }


async def run_ssh_capture(
    login: str, ws_id: str, remote_cmd: str, *, timeout: float = 60.0
) -> tuple[int, str, str]:
    """Exécute `remote_cmd` dans le workspace via SSH, capture (rc, stdout, stderr)."""
    cfg = load_global()
    argv = build_ssh_argv(
        ws_id, remote_cmd, devpod_bin=cfg.devpod.binary, key_path=devpod_ssh_key(login)
    )
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=ssh_env(login),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return (
        proc.returncode if proc.returncode is not None else -1,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )
