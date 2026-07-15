"""Partage d'une VM de test vers d'autres workspaces (accès SSH, sans cycle de vie).

Un partage :
- autorise la clé de container du workspace CIBLE dans le authorized_keys root de
  la VM (sans toucher au mot de passe root — réservé au propriétaire) ;
- écrit le bloc ~/.ssh/config du container cible (`ssh testN`) ;
- crée un message contextuel PENDING à l'attention de l'agent cible.

Le dé-partage retire la clé de la VM, le bloc ssh config et le message. Le cycle
de vie de la VM (création, suppression, resolve-ip) reste exclusivement au
workspace propriétaire.
"""
from __future__ import annotations

import asyncio

import structlog

from ..config.models import GlobalConfig, HostConfig, Hypervisor
from ..config.store import load_user
from ..db.engine import _get_engine
from ..db.test_hosts import (
    list_test_hosts_detailed,
    next_test_alias,
    set_shared_message_id,
    share_test_host,
    unshare_test_host,
)
from ..messages.renderer import build_host_context
from ..messages.service import delete_message as msg_delete
from ..messages.service import render_and_create
from .ssh_exec import run_ssh_capture
from .vm_init import (
    CONTAINER_KEYGEN_CMD,
    build_container_ssh_config_cmd,
    build_container_ssh_config_remove_cmd,
    build_vm_authorized_key_add_script,
    build_vm_authorized_key_remove_script,
)

_log = structlog.get_logger(__name__)

_NODE_SCRIPT_TIMEOUT_S = 60.0


class ShareError(Exception):
    """Échec d'une opération de partage (clé cible ou injection VM)."""


def node_for_host(cfg: GlobalConfig, host_cfg: HostConfig) -> Hypervisor | None:
    """Hyperviseur (nœud PVE) d'un host de test — même résolution que la destruction."""
    if not host_cfg.proxmox_node:
        return None
    return next((n for n in cfg.hypervisors if n.name == host_cfg.proxmox_node), None)


def _node_ssh_opts(node: Hypervisor) -> list[str]:
    """Options SSH vers le nœud PVE (mêmes réglages que routes.proxmox._ssh_opts)."""
    return [
        "-i", node.ssh_key_path,
        "-p", str(node.ssh_port),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=15",
    ]


async def _run_node_script(node: Hypervisor, script: str) -> tuple[int, str]:
    """Exécute un script `bash -s` sur le nœud PVE ; retourne (code, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "ssh",
        *_node_ssh_opts(node),
        f"{node.ssh_user}@{node.address}",
        "bash -s",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _out, serr = await asyncio.wait_for(
            proc.communicate(input=script.encode()), timeout=_NODE_SCRIPT_TIMEOUT_S
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "timeout"
    return proc.returncode or 0, serr.decode("utf-8", errors="replace")


async def _container_pubkey(login: str, workspace: str) -> str:
    """Clé publique du container d'un workspace (générée si absente, jamais régénérée)."""
    _rc, out, _err = await run_ssh_capture(login, f"{login}-{workspace}", CONTAINER_KEYGEN_CMD)
    return next((ln.strip() for ln in out.splitlines() if ln.startswith("ssh-")), "")


async def add_share(
    login: str, owner_ws: str, host_cfg: HostConfig, node: Hypervisor, target_ws: str
) -> None:
    """Partage la VM `host_cfg` vers `target_ws` : clé cible sur la VM + ssh config + message."""
    ip = host_cfg.address.split("@", 1)[-1]
    pubkey = await _container_pubkey(login, target_ws)
    if not pubkey:
        raise ShareError(f"clé publique du container {target_ws!r} introuvable")

    rc, err = await _run_node_script(
        node, build_vm_authorized_key_add_script(pubkey, host_cfg.address)
    )
    if rc != 0:
        raise ShareError(f"injection de la clé sur la VM échouée : {err[:200]}")

    engine = _get_engine()
    async with engine.begin() as conn:
        detailed = await list_test_hosts_detailed(login, target_ws, conn)
        alias = next_test_alias([a for _, a in detailed])
        await share_test_host(login, owner_ws, host_cfg.name, target_ws, alias, conn)

    cfg_rc, _o, cfg_err = await run_ssh_capture(
        login, f"{login}-{target_ws}", build_container_ssh_config_cmd(alias, ip)
    )
    if cfg_rc != 0:
        _log.warning("share_ssh_config_failed", target=target_ws, err=cfg_err[:200])

    # Message contextuel PENDING pour l'agent cible (délivrance pilotée par l'utilisateur).
    try:
        user_cfg = await load_user(login)
        ctx = build_host_context(
            owner_login=login,
            workspace_name=target_ws,
            host_name=host_cfg.name,
            alias=alias,
            address=host_cfg.address,
            culture=user_cfg.culture,
        )
        async with engine.begin() as conn:
            msg_id = await render_and_create(
                conn,
                key="test_host_available",
                culture=user_cfg.culture,
                owner_login=login,
                workspace_name=target_ws,
                msg_type="test_host",
                ctx=ctx,
            )
            if msg_id is not None:
                await set_shared_message_id(login, host_cfg.name, target_ws, msg_id, conn)
    except Exception:
        _log.warning("share_message_create_failed", target=target_ws, exc_info=True)

    _log.info(
        "test_host_shared",
        login=login,
        owner_ws=owner_ws,
        host=host_cfg.name,
        target=target_ws,
    )


async def remove_share(
    login: str, host_cfg: HostConfig, node: Hypervisor | None, target_ws: str
) -> None:
    """Retire le partage de `host_cfg` vers `target_ws` : ligne + ssh config + clé VM + message."""
    engine = _get_engine()
    async with engine.begin() as conn:
        res = await unshare_test_host(login, host_cfg.name, target_ws, conn)
    if res is None:
        return
    alias, message_id = res

    try:
        await run_ssh_capture(
            login, f"{login}-{target_ws}", build_container_ssh_config_remove_cmd(alias)
        )
    except Exception:
        _log.warning("unshare_ssh_config_cleanup_failed", target=target_ws, exc_info=True)

    # Retrait de la clé du container cible sur la VM (best-effort ; node None si VM détruite).
    if node is not None:
        pubkey = await _container_pubkey(login, target_ws)
        if pubkey:
            rc, err = await _run_node_script(
                node, build_vm_authorized_key_remove_script(pubkey, host_cfg.address)
            )
            if rc != 0:
                _log.warning("unshare_key_removal_failed", target=target_ws, err=err[:200])

    async with engine.begin() as conn:
        await msg_delete(conn, message_id)

    _log.info("test_host_unshared", login=login, host=host_cfg.name, target=target_ws)
