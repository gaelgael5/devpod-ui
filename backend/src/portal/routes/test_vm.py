"""Création d'une VM de test attachée à un workspace (lot C+D).

L'utilisateur ne fournit que l'hyperviseur et le vmid ; tous les autres args sont
figés par le paramétrage admin (`test_host_params` du type). Le host créé est marqué
`usage=tests` et associé au workspace.
"""
from __future__ import annotations

import asyncio
import re
import socket
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_user
from ..compose import service as csvc
from ..config.models import _PROXMOX_NAME_RE, GlobalConfig, HostConfig, Hypervisor
from ..config.store import load_global, load_user
from ..db.engine import _get_engine
from ..db.global_config import save_global_db
from ..db.test_hosts import (
    assign_test_host,
    get_test_host_message_id,
    list_test_hosts_detailed,
    next_test_alias,
    remove_test_host,
    set_test_host_message_id,
)
from ..devpod.ssh_exec import run_ssh_capture
from ..devpod.test_vm import (
    build_resolve_fqdn,
    build_test_host_views,
    build_test_vm_args,
    host_cert_ready,
    map_result_to_host,
    parse_last_json,
    replace_host_ip,
    substitute_param_vars,
)
from ..devpod.vm_init import (
    CONTAINER_KEYGEN_CMD,
    build_container_ssh_config_cmd,
    build_container_ssh_config_remove_cmd,
    build_portal_key_inject_script,
    build_vm_root_inject_script,
    generate_ed25519_keypair,
    generate_root_password,
)
from ..messages.renderer import build_host_context
from ..messages.service import delete_message as msg_delete
from ..messages.service import render_and_create
from ..secrets.system import delete_system_secret, store_system_cert, store_system_secret
from ..settings import get_settings
from .proxmox import (
    _fetch_spec,
    _run_destroy_script,
    _ssh_opts,
    _ssh_stream,
    _substitute,
    find_identifier_arg,
    resolve_node_script,
)

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["test-vm"])

_VMID_RE = re.compile(r"^[0-9]{1,9}$")
_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")


def _usable_type_names(cfg: GlobalConfig) -> set[str]:
    """Types d'hyperviseur prêts pour les VM de test : add_script + paramétrage."""
    return {t.name for t in cfg.hypervisor_types if t.add_script and t.test_host_params}


@router.get("/test-hypervisors")
async def list_test_hypervisors(
    user: UserInfo = Depends(require_user),
) -> list[dict[str, str]]:
    """Hyperviseurs utilisables pour créer une VM de test."""
    cfg = load_global()
    usable = _usable_type_names(cfg)
    labels = {t.name: (t.label or t.name) for t in cfg.hypervisor_types}
    return [
        {"name": n.name, "type": n.hypervisor_type, "label": labels[n.hypervisor_type]}
        for n in cfg.hypervisors
        if n.hypervisor_type in usable
    ]


@router.get("/test-hypervisors/{name}/script")
async def get_test_hypervisor_script(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    """Spec du node résolue (pour proposer les valeurs du vmid)."""
    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == name), None)
    if node is None or node.hypervisor_type not in _usable_type_names(cfg):
        raise HTTPException(status_code=404, detail=f"Test hypervisor {name!r} not available")
    return await resolve_node_script(node, cfg)


async def _init_vm_ssh(
    login: str, ws: str, host: HostConfig, node: Hypervisor, alias: str
) -> AsyncIterator[bytes]:
    """Lot E : injecte la pubkey du container et un mot de passe root dans la VM."""
    if host.type != "ssh" or not host.address:
        yield b"\n==> Init SSH ignoree (host sans adresse SSH)\n"
        return
    yield b"\n==> Initialisation SSH (cle du container + acces root)...\n"
    _rc, out, _err = await run_ssh_capture(login, f"{login}-{ws}", CONTAINER_KEYGEN_CMD)
    pubkey = next((ln.strip() for ln in out.splitlines() if ln.startswith("ssh-")), "")
    if not pubkey:
        yield b"==> ERREUR : cle publique du container introuvable\n"
        return

    password = generate_root_password()
    inject = build_vm_root_inject_script(pubkey, password, host.address)
    ssh_cmd = ["ssh", *_ssh_opts(node), f"{node.ssh_user}@{node.address}", "bash -s"]
    proc = await asyncio.create_subprocess_exec(
        *ssh_cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, serr = await asyncio.wait_for(
            proc.communicate(input=inject.encode()), timeout=60.0
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        yield b"==> ERREUR : injection SSH VM (timeout)\n"
        return
    if proc.returncode != 0:
        detail = serr.decode("utf-8", errors="replace").strip()[:300]
        yield f"==> ERREUR injection VM : {detail}\n".encode()
        return

    async with _get_engine().begin() as conn:
        await store_system_secret(
            slug=f"host.{host.name}.root-password",
            label=f"Root password — {host.name}",
            value=password,
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )
    ip = host.address.split("@", 1)[-1]
    yield (
        f"\n==> Accès SSH prêt — login: root  ip: {ip}\n"
        f"==> Mot de passe root : {password}\n"
        "==> (clé du container injectée ; mot de passe stocké côté portail)\n"
    ).encode()

    # Alias SSH persistant dans le container : `ssh testN` joint la VM (root + clé).
    cfg_rc, _cfg_out, cfg_err = await run_ssh_capture(
        login, f"{login}-{ws}", build_container_ssh_config_cmd(alias, ip)
    )
    if cfg_rc == 0:
        yield (
            f"==> Alias SSH '{alias}' ajouté au ~/.ssh/config du container "
            f"(ssh {alias})\n"
        ).encode()
    else:
        detail = cfg_err.strip()[:200]
        yield f"==> AVERTISSEMENT : alias SSH non écrit ({detail})\n".encode()

    # Activation SSH portail : génère une clé ED25519 dédiée, l'injecte dans la VM
    # et met à jour host_cert_slug — permet d'utiliser cette machine pour les services compose.
    yield b"\n==> Activation SSH portail (services compose)...\n"
    try:
        portal_priv, portal_pub = await generate_ed25519_keypair()
    except Exception as exc:
        yield f"==> AVERTISSEMENT : génération clé SSH portail échouée ({exc})\n".encode()
        return

    portal_inject = build_portal_key_inject_script(portal_pub, host.address)
    ssh_cmd2 = ["ssh", *_ssh_opts(node), f"{node.ssh_user}@{node.address}", "bash -s"]
    proc2 = await asyncio.create_subprocess_exec(
        *ssh_cmd2,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, serr2 = await asyncio.wait_for(
            proc2.communicate(input=portal_inject.encode()), timeout=30.0
        )
    except TimeoutError:
        proc2.kill()
        await proc2.wait()
        yield "==> AVERTISSEMENT : injection clé SSH portail (timeout)\n".encode()
        return
    if proc2.returncode != 0:
        detail2 = serr2.decode("utf-8", errors="replace").strip()[:300]
        yield f"==> AVERTISSEMENT : injection clé SSH portail : {detail2}\n".encode()
        return

    slug = f"compose.{host.name}"
    async with _get_engine().begin() as conn:
        await store_system_cert(
            slug=slug,
            label=f"Clé SSH portail — {host.name}",
            private_pem=portal_priv,
            public_key=portal_pub,
            cert_type="ssh",
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )
        new_cfg = load_global()
        for h in new_cfg.hosts:
            if h.name == host.name:
                h.host_cert_slug = slug
                break
        await save_global_db(new_cfg, conn)

    yield "==> SSH portail actif — services compose disponibles sur cette machine\n".encode()


@router.get("/workspaces/{ws}/test-hosts")
async def list_workspace_test_hosts(
    ws: str,
    user: UserInfo = Depends(require_user),
) -> list[dict[str, str]]:
    """Machines de test attachées à un workspace de l'utilisateur (alias, name, ip, vmid)."""
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    user_cfg = await load_user(user.login)
    if not any(w.name == ws for w in user_cfg.workspaces):
        raise HTTPException(status_code=404, detail=f"Workspace {ws!r} not found")
    async with _get_engine().connect() as conn:
        detailed = await list_test_hosts_detailed(user.login, ws, conn)
    cfg = load_global()
    return build_test_host_views(detailed, cfg.hosts)


class CreateTestVmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypervisor: str
    vmid: str


@router.post("/workspaces/{ws}/test-vm")
async def create_test_vm(
    ws: str,
    body: CreateTestVmRequest,
    user: UserInfo = Depends(require_user),
) -> StreamingResponse:
    """Crée une VM de test, l'enregistre (usage=tests) et l'associe au workspace."""
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    if not _VMID_RE.fullmatch(body.vmid):
        raise HTTPException(status_code=422, detail="vmid must be numeric")

    user_cfg = await load_user(user.login)
    if not any(w.name == ws for w in user_cfg.workspaces):
        raise HTTPException(status_code=404, detail=f"Workspace {ws!r} not found")

    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == body.hypervisor), None)
    if node is None or node.hypervisor_type not in _usable_type_names(cfg):
        raise HTTPException(
            status_code=404, detail=f"Test hypervisor {body.hypervisor!r} not available"
        )
    hyp_type = next(t for t in cfg.hypervisor_types if t.name == node.hypervisor_type)

    spec = await _fetch_spec(node, cfg)
    identifier_arg = find_identifier_arg(spec)
    if identifier_arg is None:
        raise HTTPException(status_code=422, detail="Hypervisor spec has no identifier arg")

    commands_raw: list[str] = spec.get("commands", [])  # type: ignore[assignment]
    settings = get_settings()
    login = user.login
    args = build_test_vm_args(dict(hyp_type.test_host_params), identifier_arg, body.vmid)
    args["PORTAL_URL"] = cfg.server.external_url
    args["PORTAL_TOKEN"] = settings.portal_api_key
    args["PORTAL_PVE_NODE"] = node.name

    # Substitution des variables <NOM> dans les valeurs paramétrées (ex. NODE_NAME) :
    # args (dont <NEW_VMID>) + <N>/<N+1> = nb de VM de test du workspace.
    # alias = plus petit `testN` libre (réutilise les numéros des machines supprimées).
    async with _get_engine().connect() as conn:
        detailed = await list_test_hosts_detailed(login, ws, conn)
    n = len(detailed)
    alias = next_test_alias([a for _, a in detailed])
    args = substitute_param_vars(args, {"N": str(n), "N+1": str(n + 1)})

    commands = [_substitute(c, args) for c in commands_raw]
    display = [_substitute(c, {**args, "PORTAL_TOKEN": "***"}) for c in commands_raw]

    _log.info("test_vm_create", login=login, ws=ws, node=node.name, vmid=body.vmid)

    async def _stream() -> AsyncIterator[bytes]:
        header = "==> Création VM de test\n" + "\n".join(f"    {c}" for c in display) + "\n\n"
        yield header.encode("utf-8")
        buf = bytearray()
        async for chunk in _ssh_stream(node, commands):
            buf.extend(chunk)
            yield chunk

        result: dict[str, Any] | None = parse_last_json(buf.decode("utf-8", errors="replace"))
        if result is None:
            yield b"\n==> ERREUR : pas de resultat JSON du script de creation\n"
            return
        host = map_result_to_host(result, body.vmid, node.name)
        if not host.name:
            yield b"\n==> ERREUR : le script n'a pas retourne de nom d'hote\n"
            return

        new_cfg = load_global()
        if any(h.name == host.name for h in new_cfg.hosts):
            yield f"\n==> ERREUR : un host nomme {host.name!r} existe deja\n".encode()
            return
        new_cfg.hosts.append(host)
        async with _get_engine().begin() as conn:
            await save_global_db(new_cfg, conn)
            await assign_test_host(login, ws, host.name, alias, conn)

        # Message contextuel pour les agents (non-bloquant).
        try:
            user_cfg = await load_user(login)
            ctx = build_host_context(
                owner_login=login,
                workspace_name=ws,
                host_name=host.name,
                alias=alias,
                address=host.address,
                culture=user_cfg.culture,
            )
            async with _get_engine().begin() as conn:
                msg_id = await render_and_create(
                    conn,
                    key="test_host_available",
                    culture=user_cfg.culture,
                    owner_login=login,
                    workspace_name=ws,
                    msg_type="test_host",
                    ctx=ctx,
                )
                if msg_id is not None:
                    await set_test_host_message_id(host.name, msg_id, conn)
        except Exception:
            _log.warning("test_host_message_create_failed", host=host.name, exc_info=True)

        yield (
            f"\n==> VM de test '{host.name}' creee et attachee au workspace '{ws}'\n"
        ).encode()

        async for msg in _init_vm_ssh(login, ws, host, node, alias):
            yield msg

        # Auto-start : uniquement si le SSH portail a bien été activé (host_cert_slug
        # posé par _init_vm_ssh) — sinon les services compose ne sont pas déployables.
        if host_cert_ready(load_global().hosts, host.name):
            auto_user_cfg = await load_user(login)
            async with _get_engine().begin() as conn:
                async for line in csvc.deploy_auto_start_templates(
                    conn,
                    owner_login=login,
                    secret_ns=auto_user_cfg.secret_ns,
                    node_id=host.name,
                ):
                    yield line.encode()

    return StreamingResponse(_stream(), media_type="text/plain; charset=utf-8")


@router.delete("/workspaces/{ws}/test-vm/{host_name}", status_code=204)
async def delete_test_vm(
    ws: str,
    host_name: str,
    user: UserInfo = Depends(require_user),
) -> None:
    """Supprime une machine de test : détruit la VM puis nettoie côté portail.

    Séquence résiliente : la destruction de la VM et le nettoyage du container sont
    best-effort (loggés sur échec) ; l'état portail est toujours nettoyé.
    """
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    if not _PROXMOX_NAME_RE.fullmatch(host_name):
        raise HTTPException(status_code=422, detail="Invalid host name")

    login = user.login
    async with _get_engine().connect() as conn:
        detailed = await list_test_hosts_detailed(login, ws, conn)
    alias = next((a for n, a in detailed if n == host_name), None)
    if alias is None:
        raise HTTPException(
            status_code=404, detail=f"Test host {host_name!r} not found for workspace {ws!r}"
        )

    cfg = load_global()
    host_cfg = next((h for h in cfg.hosts if h.name == host_name), None)

    # 1. Détruire la VM sur l'hyperviseur (best-effort, ne lève pas).
    if host_cfg is not None:
        await _run_destroy_script(cfg, host_cfg)

    # 2. Retirer l'alias du ~/.ssh/config du container (best-effort).
    try:
        await run_ssh_capture(
            login, f"{login}-{ws}", build_container_ssh_config_remove_cmd(alias)
        )
    except Exception:
        _log.warning("test_vm_ssh_config_cleanup_failed", host=host_name, exc_info=True)

    # 3-5. Nettoyage portail (secret root, association → libère l'alias, host config).
    async with _get_engine().begin() as conn:
        message_id = await get_test_host_message_id(host_name, conn)
        await delete_system_secret(f"host.{host_name}.root-password", conn)
        await remove_test_host(host_name, conn)
        if host_cfg is not None:
            cfg.hosts = [h for h in cfg.hosts if h.name != host_name]
            await save_global_db(cfg, conn)
        await msg_delete(conn, message_id)

    _log.info("test_vm_deleted", login=login, ws=ws, host=host_name, alias=alias)


async def _resolve_ipv4(fqdn: str) -> str:
    """Première IPv4 résolue pour `fqdn` via le resolver du portail (async)."""
    loop = asyncio.get_event_loop()
    infos = await loop.getaddrinfo(fqdn, None, family=socket.AF_INET)
    if not infos:
        raise OSError(f"no address for {fqdn}")
    return str(infos[0][4][0])


@router.post("/workspaces/{ws}/test-vm/{host_name}/resolve-ip")
async def resolve_test_vm_ip(
    ws: str,
    host_name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, str]:
    """Re-résout l'IP DHCP d'une machine de test via DNS (nom + domaine local).

    Met à jour `host.address` et le bloc `~/.ssh/config` du container.
    """
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    if not _PROXMOX_NAME_RE.fullmatch(host_name):
        raise HTTPException(status_code=422, detail="Invalid host name")

    login = user.login
    async with _get_engine().connect() as conn:
        detailed = await list_test_hosts_detailed(login, ws, conn)
    alias = next((a for n, a in detailed if n == host_name), None)
    if alias is None:
        raise HTTPException(
            status_code=404, detail=f"Test host {host_name!r} not found for workspace {ws!r}"
        )

    cfg = load_global()
    host_cfg = next((h for h in cfg.hosts if h.name == host_name), None)
    if host_cfg is None:
        raise HTTPException(status_code=404, detail=f"Host {host_name!r} not found")

    fqdn = build_resolve_fqdn(host_name, cfg.server.local_domain)
    try:
        new_ip = await _resolve_ipv4(fqdn)
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"Unresolvable: {fqdn} ({exc})") from exc

    new_address = replace_host_ip(host_cfg.address, new_ip)
    cfg.hosts = [
        h.model_copy(update={"address": new_address}) if h.name == host_name else h
        for h in cfg.hosts
    ]
    async with _get_engine().begin() as conn:
        await save_global_db(cfg, conn)

    # Réécrit le bloc ~/.ssh/config du container avec la nouvelle IP (best-effort).
    try:
        await run_ssh_capture(
            login, f"{login}-{ws}", build_container_ssh_config_cmd(alias, new_ip)
        )
    except Exception:
        _log.warning("test_vm_ssh_config_refresh_failed", host=host_name, exc_info=True)

    _log.info("test_vm_ip_resolved", login=login, ws=ws, host=host_name, fqdn=fqdn, ip=new_ip)
    return {"ip": new_ip, "fqdn": fqdn}
