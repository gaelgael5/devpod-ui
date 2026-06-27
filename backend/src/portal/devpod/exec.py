"""Façade d'exécution non-interactive dans un workspace (devpod ssh --stdio).

Service partagé par le router workspace_sessions et le backend MCP interne devpod
(façade I-1 : un point unique pour le saut réseau + mTLS, jamais de client SSH ad hoc).
"""
from __future__ import annotations

import asyncio
import os
import shlex

from ..config.store import load_global, safe_user_path
from .ssh_exec import devpod_ssh_key

# Détection du socket tmux (le devcontainer peut exposer un socket non standard).
TMUX_SOCK_DETECT = (
    "TMUX_SOCK=$(find /tmp -maxdepth 2 -name default -path '*/tmux-*/*' 2>/dev/null | head -1)"
)


def tmux(args: str) -> str:
    """Préfixe une commande tmux de la détection de socket."""
    return f'{TMUX_SOCK_DETECT}; tmux ${{TMUX_SOCK:+-S "$TMUX_SOCK"}} {args}'


async def ws_exec(
    login: str, ws_id: str, command: str, timeout: float = 30.0
) -> tuple[int, str]:
    """Exécute une commande non-interactive dans le devcontainer via SSH.

    ProxyCommand explicite (`devpod ssh --stdio`) : l'entrée ~/.ssh/config écrite par
    devpod est perdue au rebuild du conteneur portail. Retourne `(returncode, output)`
    où `output` fusionne stdout+stderr (les erreurs SSH partent souvent en stderr).
    """
    if ws_id.startswith("-"):
        raise ValueError(f"Insecure ws_id: {ws_id!r}")
    devpod_bin = load_global().devpod.binary
    proxy_cmd = f"{shlex.quote(devpod_bin)} ssh --stdio {shlex.quote(ws_id)}"
    env = {
        **dict(os.environ),
        "DEVPOD_HOME": str(safe_user_path(login, "devpod")),
        "HOME": os.environ.get("HOME", "/root"),
    }
    key_path = devpod_ssh_key(login)
    identity_args = ["-i", key_path, "-o", "IdentitiesOnly=yes"] if key_path else []
    proc = await asyncio.create_subprocess_exec(
        "ssh",
        "-o", "LogLevel=ERROR",
        "-o", "BatchMode=yes",
        *identity_args,
        "-o", f"ProxyCommand={proxy_cmd}",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "--",
        "vscode@devpod-ws",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 1, "SSH command timed out"
    output = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()
    return proc.returncode or 0, output
