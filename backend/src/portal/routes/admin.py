from __future__ import annotations

import asyncio
import re
import shlex
from typing import Literal

import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..config.models import GlobalConfig, HostConfig, Hypervisor
from ..config.store import _data_root, load_global
from ..db.engine import get_conn
from ..db.global_config import save_global_db
from ..db.tables import harpo_certificates
from ..db.tables import workspace_status as _ws_status_table
from ..db.tables import workspaces as _ws_table
from ..secrets.system import (
    delete_system_cert,
    delete_system_secret,
    store_system_cert,
    store_system_secret,
)

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])

# user@host : user alphanum+_- (max 32), host alphanum+._- (max 253) — aucun apostrophe
_ADDRESS_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}@[a-zA-Z0-9][a-zA-Z0-9._-]{0,253}$")


# ─── DTOs ─────────────────────────────────────────────────────────────────────


class HostCreateRequest(BaseModel):
    """DTO d'entrée pour add/update host — accepte les valeurs brutes de secrets."""

    model_config = ConfigDict(extra="forbid")

    name: str
    default: bool = False
    type: Literal["docker-tls", "ssh"]
    docker_host: str = ""
    address: str = ""
    proxmox_node: str = ""
    vmid: str = ""
    ci_password: str = ""  # valeur brute, stockée dans harpo au CREATE/UPDATE


class BootstrapSshRequest(BaseModel):
    address: str  # user@host — ex: debian@192.168.10.179
    proxmox_node: str = ""  # optionnel si host.proxmox_node est déjà connu


# ─── Config ───────────────────────────────────────────────────────────────────


@router.get("/config")
async def get_admin_config(user: UserInfo = Depends(require_admin)) -> dict[str, object]:
    cfg = load_global()
    return cfg.model_dump(mode="json")


@router.put("/config")
async def put_admin_config(
    updates: dict[str, object], user: UserInfo = Depends(require_admin)
) -> dict[str, object]:
    cfg = load_global()
    merged: dict[str, object] = cfg.model_dump(mode="json")
    merged.update(updates)
    try:
        new_cfg = GlobalConfig.model_validate(merged)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from ..db.engine import _get_engine

    async with _get_engine().begin() as conn:
        await save_global_db(new_cfg, conn)
    _log.info("global_config_updated", by=user.login)
    return new_cfg.model_dump(mode="json")


# ─── Hosts CRUD ───────────────────────────────────────────────────────────────


@router.get("/hosts")
async def list_hosts(user: UserInfo = Depends(require_admin)) -> list[dict[str, object]]:
    cfg = load_global()
    return [h.model_dump(mode="json") for h in cfg.hosts]


@router.post("/hosts", status_code=201)
async def add_host(
    body: HostCreateRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    cfg = load_global()
    if any(h.name == body.name for h in cfg.hosts):
        raise HTTPException(status_code=409, detail=f"Host {body.name!r} already exists")

    ci_slug = ""
    if body.ci_password:
        ci_slug = f"host.{body.name}.ci-password"
        await store_system_secret(
            slug=ci_slug,
            label=f"CI password — {body.name}",
            value=body.ci_password,
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )

    host = HostConfig(
        name=body.name,
        default=body.default,
        type=body.type,
        docker_host=body.docker_host,
        address=body.address,
        proxmox_node=body.proxmox_node,
        vmid=body.vmid,
        ci_password_secret_slug=ci_slug,
        host_cert_slug="",
        storage_type="local",
        vault_identifier="",
    )
    cfg.hosts.append(host)
    await save_global_db(cfg, conn)
    _log.info("host_added", name=body.name, by=user.login)
    return host.model_dump(mode="json")


@router.put("/hosts/{name}")
async def update_host(
    name: str,
    body: HostCreateRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, object]:
    if body.name != name:
        raise HTTPException(status_code=422, detail="Host name in body must match URL")
    cfg = load_global()
    idx = next((i for i, h in enumerate(cfg.hosts) if h.name == name), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")

    existing = cfg.hosts[idx]
    ci_slug = existing.ci_password_secret_slug

    # Si un nouveau ci_password est fourni, remplacer dans harpo (store est idempotent)
    if body.ci_password:
        ci_slug = f"host.{name}.ci-password"
        await store_system_secret(
            slug=ci_slug,
            label=f"CI password — {name}",
            value=body.ci_password,
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )

    host = HostConfig(
        name=body.name,
        default=body.default,
        type=body.type,
        docker_host=body.docker_host,
        address=body.address,
        proxmox_node=body.proxmox_node,
        vmid=body.vmid,
        ci_password_secret_slug=ci_slug,
        host_cert_slug=existing.host_cert_slug,  # conservé
        storage_type="local",
        vault_identifier="",
    )
    cfg.hosts[idx] = host
    await save_global_db(cfg, conn)
    _log.info("host_updated", name=name, by=user.login)
    return host.model_dump(mode="json")


@router.delete("/hosts/{name}", status_code=204)
async def delete_host(
    name: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    cfg = load_global()
    host_cfg = next((h for h in cfg.hosts if h.name == name), None)
    if host_cfg is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")

    # 1. Supprimer tous les workspaces sur ce host.
    # host="" = "hôte par défaut" dans le formulaire de création. Si le host supprimé
    # est le default, ces workspaces lui appartiennent aussi.
    from sqlalchemy import or_

    host_condition = _ws_table.c.host == name
    if host_cfg.default:
        host_condition = or_(host_condition, _ws_table.c.host == "")
    rows = (
        await conn.execute(select(_ws_table.c.login, _ws_table.c.name).where(host_condition))
    ).mappings().all()

    if rows:
        from .workspace_ops import _get_service

        svc = _get_service()

        async def _delete_one(login: str, ws_name: str) -> None:
            ws_id = f"{login}-{ws_name}"
            try:
                await svc.delete(login=login, ws_id=ws_id, shelve=False)
            except Exception:
                _log.warning("host_delete_ws_failed", host=name, ws_id=ws_id, exc_info=True)
            finally:
                # Toujours supprimer la config du workspace, même si devpod delete a échoué.
                # svc.delete() purge workspace_status mais jamais la table workspaces.
                await conn.execute(
                    sql_delete(_ws_table)
                    .where(_ws_table.c.login == login)
                    .where(_ws_table.c.name == ws_name)
                )

        await asyncio.gather(*[_delete_one(r["login"], r["name"]) for r in rows])

    # 2. Exécuter le destroy_script de l'hyperviseur (si VM gérée par Proxmox)
    from .proxmox import _run_destroy_script

    await _run_destroy_script(cfg, host_cfg)

    # 3. Nettoyer les secrets harpo avant de retirer le host
    if host_cfg.ci_password_secret_slug:
        await delete_system_secret(host_cfg.ci_password_secret_slug, conn)
    if host_cfg.host_cert_slug:
        await delete_system_cert(host_cfg.host_cert_slug, conn)

    # 4. Retirer le host de la config
    cfg.hosts = [h for h in cfg.hosts if h.name != name]
    await save_global_db(cfg, conn)
    _log.info("host_deleted", name=name, by=user.login, workspaces_deleted=len(rows))


@router.get("/hosts/{name}/workspaces")
async def list_host_workspaces(
    name: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, object]]:
    """Retourne les workspaces du host groupés par utilisateur, avec leur statut."""
    from sqlalchemy import func as _func

    ws_id_expr = _func.concat(_ws_table.c.login, "-", _ws_table.c.name)
    rows = (
        await conn.execute(
            select(
                _ws_table.c.login,
                _ws_table.c.name,
                _ws_status_table.c.status,
            )
            .select_from(
                _ws_table.outerjoin(
                    _ws_status_table, _ws_status_table.c.ws_id == ws_id_expr
                )
            )
            .where(_ws_table.c.host == name)
            .order_by(_ws_table.c.login, _ws_table.c.name)
        )
    ).mappings().all()

    by_login: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_login.setdefault(r["login"], []).append(
            {"name": r["name"], "status": r["status"] or "unknown"}
        )

    return [{"login": login, "workspaces": wss} for login, wss in by_login.items()]


# ─── Bootstrap SSH ────────────────────────────────────────────────────────────


@router.post("/hosts/{name}/bootstrap-ssh")
async def bootstrap_host_ssh(
    name: str,
    body: BootstrapSshRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    """Configure un host SSH : génère paire ed25519, stocke dans harpo, injecte la pubkey via PVE.

    Flux : portail → SSH PVE → SSH VM → ~/.ssh/authorized_keys
    Idempotent : l'injection n'ajoute la clé que si elle n'est pas déjà présente.
    La clé privée ne sort JAMAIS de cette route.
    """
    if not _ADDRESS_RE.fullmatch(body.address):
        raise HTTPException(status_code=422, detail="address invalide (attendu : user@host)")

    cfg = load_global()
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} introuvable")
    if host.type != "ssh":
        raise HTTPException(
            status_code=422,
            detail="bootstrap-ssh disponible pour les hosts de type ssh uniquement",
        )

    # Résolution du nœud PVE : corps de la requête → host.proxmox_node → 422
    resolved_pve = body.proxmox_node or host.proxmox_node
    if not resolved_pve:
        raise HTTPException(
            status_code=422,
            detail="proxmox_node requis (non mémorisé sur le host)",
        )
    pve_node = next((n for n in cfg.hypervisors if n.name == resolved_pve), None)
    if pve_node is None:
        raise HTTPException(status_code=404, detail=f"Nœud Proxmox {resolved_pve!r} introuvable")

    # Génère une paire ed25519 en mémoire (jamais sur disque)
    private_key_obj = Ed25519PrivateKey.generate()
    private_pem = private_key_obj.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_key = (
        private_key_obj.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode()
        .strip()
    )

    # La clé SSH du host est un secret d'infrastructure : toujours local (PORTAL_VAULT_KEK).
    # Le portail doit y accéder à runtime sans PIN utilisateur.
    cert_slug = f"host.{name}.cert"
    await store_system_cert(
        slug=cert_slug,
        label=f"SSH key — {name}",
        private_pem=private_pem,
        public_key=public_key,
        cert_type="ssh-ed25519",
        storage_type="local",
        vault_identifier="",
        conn=conn,
    )

    # Injecte la pubkey dans la VM via un saut PVE
    inner_cmd = (
        "mkdir -p ~/.ssh && "
        "chmod 700 ~/.ssh && "
        f"grep -qxF {shlex.quote(public_key)} ~/.ssh/authorized_keys 2>/dev/null || "
        f"echo {shlex.quote(public_key)} >> ~/.ssh/authorized_keys && "
        "chmod 600 ~/.ssh/authorized_keys"
    )
    inject_script = (
        "set -euo pipefail\n"
        f"ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes "
        f"-o ConnectTimeout=15 {shlex.quote(body.address)} {shlex.quote(inner_cmd)}\n"
    )

    from .proxmox import _ssh_opts

    proc = await asyncio.create_subprocess_exec(
        "ssh",
        *_ssh_opts(pve_node),
        f"{pve_node.ssh_user}@{pve_node.address}",
        "bash -s",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(input=inject_script.encode()), timeout=30.0
        )
    except TimeoutError:
        proc.kill()
        raise HTTPException(status_code=504, detail="Injection de clé SSH : timeout") from None
    if proc.returncode != 0:
        msg = stderr.decode("utf-8", errors="replace").strip()
        raise HTTPException(
            status_code=502, detail=f"Injection de clé SSH échouée : {msg or '(no stderr)'}"
        )

    # Met à jour address, proxmox_node et host_cert_slug dans le config
    idx = next(i for i, h in enumerate(cfg.hosts) if h.name == name)
    cfg.hosts[idx] = cfg.hosts[idx].model_copy(
        update={
            "address": body.address,
            "proxmox_node": resolved_pve,
            "host_cert_slug": cert_slug,
        }
    )
    await save_global_db(cfg, conn)

    _log.info("host_ssh_bootstrapped", host=name, address=body.address, by=user.login)
    return {"public_key": public_key, "address": body.address, "host_cert_slug": cert_slug}


# ─── Cert ─────────────────────────────────────────────────────────────────────


@router.get("/hosts/{name}/cert")
async def get_host_cert(
    name: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    """Retourne la clé publique (SSH) ou les fichiers TLS (docker-tls) du host.

    SSH  : lit depuis harpo_certificates — retourne public_key + cert_type.
    TLS  : lit ca.pem + cert.pem depuis cfg.devpod.client_cert_path.
    Seuls les fichiers publics sont exposés (jamais la clé privée).
    """
    cfg = load_global()
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")

    if host.type == "ssh":
        if not host.host_cert_slug:
            raise HTTPException(
                status_code=404,
                detail="Clé SSH non configurée (lancez bootstrap-ssh)",
            )
        row = (
            await conn.execute(
                select(harpo_certificates)
                .where(harpo_certificates.c.owner_login == "__system__")
                .where(harpo_certificates.c.slug == host.host_cert_slug)
            )
        ).mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Cert introuvable en base")
        return {"public_key": str(row["public_key"]), "cert_type": str(row["cert_type"])}

    # docker-tls : lire depuis le répertoire de certs global
    raw_path = cfg.devpod.client_cert_path
    if not raw_path:
        raise HTTPException(status_code=422, detail="client_cert_path non configuré")

    from pathlib import Path

    cert_dir = Path(raw_path).resolve()
    data_root = _data_root().resolve()
    if not cert_dir.is_relative_to(data_root):
        raise HTTPException(status_code=403, detail="Chemin cert non autorisé (hors /data)")

    result: dict[str, str] = {}
    for cert_name in ("ca.pem", "cert.pem"):
        cert_file = cert_dir / cert_name
        if cert_file.exists():
            result[cert_name] = cert_file.read_text(encoding="utf-8")

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun fichier de certificat trouvé dans {raw_path}",
        )
    return result


# ─── SSH helper (conservé pour les WebSocket SSH proxy) ──────────────────────


async def _run_script_on_pve(node: Hypervisor, script: str, timeout: float = 30.0) -> str:
    """Exécute un script bash sur un nœud PVE via SSH stdin ; lève RuntimeError si erreur."""
    from .proxmox import _ssh_opts

    proc = await asyncio.create_subprocess_exec(
        "ssh",
        *_ssh_opts(node),
        f"{node.ssh_user}@{node.address}",
        "bash -s",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=script.encode()), timeout=timeout
        )
    except TimeoutError:
        proc.kill()
        raise
    if proc.returncode != 0:
        msg = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"SSH script exited {proc.returncode}: {msg or '(no stderr)'}")
    return stdout.decode("utf-8", errors="replace")
