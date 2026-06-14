from __future__ import annotations

import asyncio
import contextlib
import os
import re
import tempfile
from pathlib import Path

import structlog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_ssh_private_key,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth.rbac import UserInfo, require_admin, require_admin_or_api_key
from ..config.models import GlobalConfig, HostConfig, Hypervisor
from ..config.store import _data_root, load_global, save_global

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])

# user@host : user alphanum+_- (max 32), host alphanum+._- (max 253) — aucun apostrophe
_ADDRESS_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}@[a-zA-Z0-9][a-zA-Z0-9._-]{0,253}$")


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
    save_global(new_cfg)
    _log.info("global_config_updated", by=user.login)
    return new_cfg.model_dump(mode="json")


@router.get("/hosts")
async def list_hosts(user: UserInfo = Depends(require_admin)) -> list[dict[str, object]]:
    cfg = load_global()
    return [h.model_dump(mode="json") for h in cfg.hosts]


@router.post("/hosts", status_code=201)
async def add_host(host: HostConfig, user: UserInfo = Depends(require_admin)) -> dict[str, object]:
    cfg = load_global()
    if any(h.name == host.name for h in cfg.hosts):
        raise HTTPException(status_code=409, detail=f"Host {host.name!r} already exists")
    cfg.hosts.append(host)
    save_global(cfg)
    _log.info("host_added", name=host.name, by=user.login)
    return host.model_dump(mode="json")


@router.put("/hosts/{name}")
async def update_host(
    name: str, host: HostConfig, user: UserInfo = Depends(require_admin)
) -> dict[str, object]:
    if host.name != name:
        raise HTTPException(status_code=422, detail="Host name in body must match URL")
    cfg = load_global()
    idx = next((i for i, h in enumerate(cfg.hosts) if h.name == name), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")
    cfg.hosts[idx] = host
    save_global(cfg)
    _log.info("host_updated", name=name, by=user.login)
    return host.model_dump(mode="json")


@router.delete("/hosts/{name}", status_code=204)
async def delete_host(name: str, user: UserInfo = Depends(require_admin)) -> None:
    cfg = load_global()
    before = len(cfg.hosts)
    cfg.hosts = [h for h in cfg.hosts if h.name != name]
    if len(cfg.hosts) == before:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")
    save_global(cfg)
    _log.info("host_deleted", name=name, by=user.login)


@router.post("/hosts/{name}/generate-ssh-key")
async def generate_host_ssh_key(
    name: str,
    address: str | None = Query(default=None),
    proxmox_node: str | None = Query(default=None),
    user: UserInfo = Depends(require_admin_or_api_key),
) -> dict[str, str]:
    """Génère une paire ed25519 pour le host SSH, stocke la privée dans /data/keys/hosts/.

    Idempotent : si la clé existe déjà, retourne la pub sans régénérer.
    Si `address` est fourni, met à jour host.address dans config.yaml.
    Si `proxmox_node` est fourni, mémorise le nœud PVE d'origine.
    """
    cfg = load_global()
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")
    if host.type != "ssh":
        raise HTTPException(
            status_code=422,
            detail="Génération de clé SSH disponible pour les hosts de type ssh uniquement",
        )

    key_path = _data_root() / "keys" / "hosts" / f"{name}_ed25519"
    public_key = _generate_or_load_key(key_path, name, user.login)

    updates: dict[str, str] = {}
    if not host.key_path:
        updates["key_path"] = str(key_path)
    if address is not None:
        updates["address"] = address
    if proxmox_node is not None:
        updates["proxmox_node"] = proxmox_node

    if updates:
        idx = next(i for i, h in enumerate(cfg.hosts) if h.name == name)
        cfg.hosts[idx] = cfg.hosts[idx].model_copy(update=updates)
        save_global(cfg)

    return {"public_key": public_key}


async def _run_script_on_pve(node: Hypervisor, script: str, timeout: float = 30.0) -> str:
    """Exécute un script bash sur un nœud PVE via SSH stdin ; lève RuntimeError si erreur."""
    from .proxmox import _ssh_opts
    proc = await asyncio.create_subprocess_exec(
        "ssh", *_ssh_opts(node), f"{node.ssh_user}@{node.address}",
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


def _generate_or_load_key(key_path: Path, host_name: str, requester: str) -> str:
    """Génère la clé ed25519 si absente, retourne la clé publique OpenSSH."""
    key_dir = key_path.parent
    key_dir.mkdir(parents=True, exist_ok=True)

    if not key_path.exists():
        private_key = Ed25519PrivateKey.generate()
        private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
        fd, tmp_path = tempfile.mkstemp(dir=key_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(private_pem)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, str(key_path))
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
        _log.info("host_ssh_key_generated", host=host_name, by=requester)

    raw = load_ssh_private_key(key_path.read_bytes(), password=None)
    pub_bytes = raw.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    return pub_bytes.decode().strip()


@router.get("/hosts/{name}/cert")
async def get_host_cert(
    name: str, user: UserInfo = Depends(require_admin)
) -> dict[str, str]:
    """Retourne le contenu de ca.pem et cert.pem du répertoire key_path du host.

    Seuls les fichiers publics sont exposés (jamais key.pem).
    Le chemin doit être sous _data_root() pour prévenir toute fuite hors /data.
    """
    cfg = load_global()
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")
    if host.type != "docker-tls":
        raise HTTPException(
            status_code=422,
            detail="Certificats TLS disponibles pour les hosts docker-tls uniquement",
        )

    raw_path = host.key_path or cfg.devpod.client_cert_path
    if not raw_path:
        raise HTTPException(status_code=422, detail="key_path non configuré pour ce host")

    cert_dir = Path(raw_path).resolve()
    data_root = _data_root().resolve()
    if not cert_dir.is_relative_to(data_root):
        raise HTTPException(status_code=422, detail="key_path doit être sous le répertoire /data")

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


# ── Bootstrap SSH ─────────────────────────────────────────────────────────────

class BootstrapSshRequest(BaseModel):
    address: str  # user@host — ex: debian@192.168.10.179
    proxmox_node: str = ""  # optionnel si host.proxmox_node est déjà connu


@router.post("/hosts/{name}/bootstrap-ssh")
async def bootstrap_host_ssh(
    name: str,
    body: BootstrapSshRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, str]:
    """Configure un host SSH : génère/récupère la clé ed25519 et injecte la pubkey via PVE.

    Flux : portail → SSH PVE → SSH VM → ~/.ssh/authorized_keys
    Idempotent : l'injection n'ajoute la clé que si elle n'est pas déjà présente.
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
        raise HTTPException(
            status_code=404, detail=f"Nœud Proxmox {resolved_pve!r} introuvable"
        )

    # Génère ou charge la clé ed25519
    key_path = _data_root() / "keys" / "hosts" / f"{name}_ed25519"
    public_key = _generate_or_load_key(key_path, name, user.login)

    # Met à jour address + key_path + proxmox_node dans le config
    idx = next(i for i, h in enumerate(cfg.hosts) if h.name == name)
    cfg.hosts[idx] = cfg.hosts[idx].model_copy(
        update={"address": body.address, "key_path": str(key_path), "proxmox_node": resolved_pve}
    )
    save_global(cfg)

    # Injecte la pubkey dans la VM via un saut PVE
    # Sécurité du quoting : pubkey ed25519 = alphanum + "+/= " (pas d'apostrophe) ;
    # address = user@host alphanum + "@._-" (pas d'apostrophe) → single-quote safe.
    inner_cmd = (
        "mkdir -p ~/.ssh && "
        "chmod 700 ~/.ssh && "
        f'grep -qxF "{public_key}" ~/.ssh/authorized_keys 2>/dev/null || '
        f'echo "{public_key}" >> ~/.ssh/authorized_keys && '
        "chmod 600 ~/.ssh/authorized_keys"
    )
    inject_script = (
        "set -euo pipefail\n"
        f"ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes "
        f"-o ConnectTimeout=15 '{body.address}' '{inner_cmd}'\n"
    )

    try:
        await _run_script_on_pve(pve_node, inject_script, timeout=30.0)
    except (TimeoutError, RuntimeError) as exc:
        _log.warning("host_ssh_bootstrap_inject_failed", host=name, error=str(exc))
        raise HTTPException(
            status_code=502, detail=f"Injection de clé SSH échouée : {exc}"
        ) from exc

    _log.info("host_ssh_bootstrapped", host=name, address=body.address, by=user.login)
    return {"public_key": public_key, "address": body.address, "key_path": str(key_path)}
