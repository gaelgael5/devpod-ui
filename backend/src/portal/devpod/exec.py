"""Façade d'exécution non-interactive dans un workspace (devpod ssh --stdio).

Service partagé par le router workspace_sessions et le backend MCP interne devpod
(façade I-1 : un point unique pour le saut réseau + mTLS, jamais de client SSH ad hoc).
"""

from __future__ import annotations

import asyncio
import os
import shlex

import structlog

from ..config.store import load_global, safe_user_path
from .ssh_exec import control_ssh_args, devpod_ssh_key

_log = structlog.get_logger(__name__)

# rc de timeout de ws_exec — 124 (convention GNU timeout), distinct des codes
# porteurs de sens pour les sondes : 0 (ok), 1 (tmux sans serveur), 127 (commande
# absente), 255 (échec de transport SSH). Un rc=1 de timeout serait indistinguable
# d'un « aucun serveur tmux » (bug 807fed1c : injoignable confondu avec vide).
TIMEOUT_RC = 124

# rc de sonde tmux signifiant « joignable mais aucun serveur tmux » : 1 = pas de
# serveur sur le socket, 127 = tmux non installé dans le conteneur.
NO_TMUX_SERVER_RCS = (1, 127)

# Détection du socket tmux (le devcontainer peut exposer un socket non standard).
TMUX_SOCK_DETECT = (
    "TMUX_SOCK=$(find /tmp -maxdepth 2 -name default -path '*/tmux-*/*' 2>/dev/null | head -1)"
)


def tmux(args: str) -> str:
    """Préfixe une commande tmux de la détection de socket."""
    return f'{TMUX_SOCK_DETECT}; tmux ${{TMUX_SOCK:+-S "$TMUX_SOCK"}} {args}'


def remote_tmux_command(session: str) -> str:
    """Commande shell distante : session tmux persistante, fallback shell simple.

    Pour un host/VM (socket tmux par défaut de l'utilisateur SSH — pas de
    détection de socket, réservée aux devcontainers). `new-session -A` attache
    si la session existe, crée sinon. tmux absent → bash, avec un mot d'excuse.
    """
    return (
        f"command -v tmux >/dev/null 2>&1 && exec tmux new-session -A -s {shlex.quote(session)}"
        " || { echo '[portal] tmux absent : session non persistante'; exec bash -l; }"
    )


async def ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0) -> tuple[int, str]:
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
        "-o",
        "LogLevel=ERROR",
        "-o",
        "BatchMode=yes",
        *identity_args,
        *control_ssh_args(ws_id),
        "-o",
        f"ProxyCommand={proxy_cmd}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
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
        # Libellé = contrat : create_session détecte le timeout par sous-chaîne.
        return TIMEOUT_RC, "SSH command timed out"
    output = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()
    return proc.returncode or 0, output


async def warm_tunnel(login: str, ws_id: str, *, timeout: float = 20.0) -> bool:
    """Pré-chauffe le tunnel SSH d'un workspace : monte le ControlMaster en fond.

    Lance un `true` via `ws_exec` — le premier appel établit le master partagé
    (handshake mTLS via devpod), les ouvertures de terminal suivantes s'y rattachent
    instantanément. Idempotent et bon marché si déjà chaud (simple rattachement).
    Best-effort : ne lève jamais, n'émet aucun secret. Retourne True si le tunnel
    est chaud (rc 0).
    """
    try:
        rc, _out = await ws_exec(login, ws_id, "true", timeout=timeout)
    except Exception:
        _log.warning("ssh_warm_tunnel_failed", ws_id=ws_id, exc_info=True)
        return False
    if rc != 0:
        _log.info("ssh_warm_tunnel_cold", ws_id=ws_id, rc=rc)
    return rc == 0
