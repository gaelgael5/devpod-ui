"""Synchronisation de l'arborescence agent-config vers les hosts (spec 35 §4.2).

Canal v1 : hosts de type « ssh » uniquement (tar streamé sur stdin + script de
dépose). Les hosts « docker-tls » n'exposent aucun accès filesystem (seul le
daemon mTLS :2376 est joignable) — le provisioning les rejette explicitement
(spec 35 §10) en attendant un canal via l'API Docker.

Sémantique de dépose (rejouable, testée en local dans test_sync.py) :
- le répertoire {ws_id} est la source d'un bind mount → jamais recréé (inode stable) ;
- extraction dans un staging .sync.XXXXXX sur le même filesystem, puis mv par
  fichier (rename atomique) — un resync ne corrompt jamais un fichier lu par le
  conteneur ;
- les sous-répertoires d'agents retirés du spec sont purgés (liste d'agents
  attendus embarquée dans le script).

Les identifiants embarqués dans les scripts sont validés par regex stricte AVANT
insertion (ws_id, agent ids) — aucune valeur libre n'atteint le shell distant.
"""

from __future__ import annotations

import asyncio
import io
import tarfile
from pathlib import Path

import structlog

from .models import AGENT_ID_RE
from .tree import WS_ID_RE

_log = structlog.get_logger(__name__)

# Relatif au $HOME de l'utilisateur SSH du host (résolu côté host par le script,
# côté portail par resolve_remote_home pour écrire la source du bind mount).
AGENT_CONFIG_ROOT = ".devpod-portal/agent-config"

_SSH_BASE_OPTS = [
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=15",
]


class AgentSyncError(Exception):
    pass


def _checked_ws_id(ws_id: str) -> str:
    if not WS_ID_RE.fullmatch(ws_id):
        raise AgentSyncError(f"ws_id invalide : {ws_id!r}")
    return ws_id


def build_ws_tarball(ws_dir: Path) -> bytes:
    """Archive gzip du répertoire du workspace (arcname = ws_id, modes préservés)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(ws_dir, arcname=ws_dir.name, recursive=True)
    return buf.getvalue()


def build_sync_script(ws_id: str, agent_ids: list[str]) -> str:
    """Script de dépose exécuté sur le host, tar gzip attendu sur stdin.

    Les boucles `for` sur la sortie de find sont sûres : agent ids et filenames
    sont contraints par regex sans blanc ni quote (validés portail-side).
    """
    _checked_ws_id(ws_id)
    for aid in agent_ids:
        if not AGENT_ID_RE.fullmatch(aid):
            raise AgentSyncError(f"agent id invalide : {aid!r}")
    # Motif case jamais vrai quand aucun agent n'est attendu (tout est purgé).
    keep = "|".join(f"'{aid}'" for aid in agent_ids) or "'.no-agent.'"
    return f"""set -eu
ROOT="$HOME/{AGENT_CONFIG_ROOT}"
WS='{ws_id}'
mkdir -p "$ROOT"
chmod 700 "$ROOT" "$HOME/.devpod-portal"
TMP=$(mktemp -d "$ROOT/.sync.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
tar xzf - -C "$TMP"
mkdir -p "$ROOT/$WS"
chmod 700 "$ROOT/$WS"
cd "$TMP/$WS"
for d in $(find . -mindepth 1 -type d); do
  mkdir -p "$ROOT/$WS/$d"
  chmod 700 "$ROOT/$WS/$d"
done
for f in $(find . -type f); do
  mv -f "$f" "$ROOT/$WS/$f"
done
cd "$ROOT/$WS"
for e in * .[!.]* ..?*; do
  [ -e "$e" ] || continue
  case "$e" in
    {keep}) ;;
    *) rm -rf "./$e" ;;
  esac
done
"""


def build_purge_script(ws_id: str) -> str:
    """Suppression de l'arborescence du workspace (delete du workspace)."""
    _checked_ws_id(ws_id)
    return f"""set -eu
WS='{ws_id}'
rm -rf "$HOME/{AGENT_CONFIG_ROOT}/$WS"
"""


async def resolve_remote_home(ssh_user: str, ssh_host: str, ssh_key_path: str) -> str:
    """$HOME réel de l'utilisateur SSH — sert de base à la source du bind mount."""
    proc = await asyncio.create_subprocess_exec(
        "ssh",
        "-i",
        ssh_key_path,
        *_SSH_BASE_OPTS,
        f"{ssh_user}@{ssh_host}",
        "echo $HOME",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    home = out.decode().strip()
    if proc.returncode != 0 or not home.startswith("/"):
        raise AgentSyncError(
            f"résolution du home SSH impossible sur {ssh_host!r} (code {proc.returncode})"
        )
    return home


async def _run_remote(
    script: str,
    *,
    ssh_user: str,
    ssh_host: str,
    ssh_key_path: str,
    stdin: bytes | None,
) -> None:
    proc = await asyncio.create_subprocess_exec(
        "ssh",
        "-i",
        ssh_key_path,
        *_SSH_BASE_OPTS,
        f"{ssh_user}@{ssh_host}",
        script,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate(input=stdin)
    if proc.returncode != 0:
        raise AgentSyncError(
            f"synchronisation agent-config sur {ssh_host!r} échouée : "
            f"{err.decode(errors='replace').strip()}"
        )


async def push_tree_ssh(
    ws_dir: Path,
    agent_ids: list[str],
    *,
    ssh_user: str,
    ssh_host: str,
    ssh_key_path: str,
) -> None:
    """Pousse l'arborescence stagée localement vers le host SSH."""
    script = build_sync_script(ws_dir.name, agent_ids)
    blob = await asyncio.to_thread(build_ws_tarball, ws_dir)
    await _run_remote(
        script, ssh_user=ssh_user, ssh_host=ssh_host, ssh_key_path=ssh_key_path, stdin=blob
    )
    _log.info(
        "agent_config_pushed",
        ws_id=ws_dir.name,
        host=ssh_host,
        agents=agent_ids,
    )


async def purge_tree_ssh(
    ws_id: str,
    *,
    ssh_user: str,
    ssh_host: str,
    ssh_key_path: str,
) -> None:
    """Purge l'arborescence du workspace sur le host (delete du workspace)."""
    await _run_remote(
        build_purge_script(ws_id),
        ssh_user=ssh_user,
        ssh_host=ssh_host,
        ssh_key_path=ssh_key_path,
        stdin=None,
    )
    _log.info("agent_config_purged", ws_id=ws_id, host=ssh_host)
