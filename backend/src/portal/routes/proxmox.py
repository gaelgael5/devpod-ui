from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth.rbac import UserInfo, require_admin
from ..config.models import _PROXMOX_NAME_RE, ProxmoxNode
from ..config.store import load_global, save_global

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])

_MAX_KEY_BYTES = 16 * 1024  # 16 Ko — largement suffisant pour une clé SSH


def _data_root() -> Path:
    return Path(os.environ.get("PORTAL_DATA_ROOT", "/data"))


def _key_dir() -> Path:
    p = _data_root() / "ssh_keys" / "proxmox"
    p.mkdir(parents=True, exist_ok=True)
    p.chmod(0o700)  # répertoire owner-only, indépendamment du umask
    return p


def _write_key_atomic(key_path: Path, key_bytes: bytes) -> None:
    """Écrit la clé SSH de façon atomique avec permissions 0o600."""
    tmp = key_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)  # nettoie un éventuel résidu
    try:
        # O_CREAT | O_EXCL | mode=0o600 : permissions définitives dès la création,
        # pas de fenêtre avec des droits trop larges (umask ignoré pour les bits donnés).
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key_bytes)
        tmp.rename(key_path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _validate_key_bytes(key_bytes: bytes) -> None:
    if len(key_bytes) > _MAX_KEY_BYTES:
        raise HTTPException(status_code=413, detail="SSH key file too large (max 16 KB)")
    if not key_bytes.startswith(b"-----BEGIN"):
        raise HTTPException(status_code=422, detail="SSH key must be a PEM-encoded private key")


@router.get("/proxmox")
async def list_proxmox_nodes(
    user: UserInfo = Depends(require_admin),
) -> list[dict[str, object]]:
    cfg = load_global()
    return [n.model_dump(mode="json") for n in cfg.proxmox_nodes]


@router.post("/proxmox", status_code=201)
async def add_proxmox_node(
    name: str = Form(...),
    address: str = Form(...),
    ssh_user: str = Form("root"),
    ssh_port: int = Form(22),
    pve_node: str = Form("pve"),
    script_url: str = Form(""),
    ssh_key: UploadFile = File(...),
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    if not _PROXMOX_NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=422,
            detail=f"name {name!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$",
        )

    cfg = load_global()
    if any(n.name == name for n in cfg.proxmox_nodes):
        raise HTTPException(status_code=409, detail=f"Proxmox node {name!r} already exists")

    key_bytes = await ssh_key.read(_MAX_KEY_BYTES + 1)
    _validate_key_bytes(key_bytes)

    key_path = _key_dir() / name
    _write_key_atomic(key_path, key_bytes)

    node = ProxmoxNode(
        name=name,
        address=address,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_key_path=str(key_path),
        pve_node=pve_node,
        script_url=script_url,
    )
    cfg.proxmox_nodes.append(node)
    save_global(cfg)
    _log.info("proxmox_node_added", name=name, address=address, by=user.login)
    return node.model_dump(mode="json")


@router.put("/proxmox/{name}", status_code=200)
async def update_proxmox_node(
    name: str,
    address: str = Form(...),
    ssh_user: str = Form("root"),
    ssh_port: int = Form(22),
    pve_node: str = Form("pve"),
    script_url: str = Form(""),
    ssh_key: Optional[UploadFile] = File(default=None),
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    cfg = load_global()
    node = next((n for n in cfg.proxmox_nodes if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Proxmox node {name!r} not found")

    key_path = node.ssh_key_path  # conserve la clé existante par défaut

    if ssh_key is not None:
        key_bytes = await ssh_key.read(_MAX_KEY_BYTES + 1)
        if key_bytes:  # vide = pas de remplacement
            _validate_key_bytes(key_bytes)
            _write_key_atomic(Path(key_path), key_bytes)

    updated = ProxmoxNode(
        name=name,
        address=address,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_key_path=key_path,
        pve_node=pve_node,
        script_url=script_url,
    )
    cfg.proxmox_nodes = [updated if n.name == name else n for n in cfg.proxmox_nodes]
    save_global(cfg)
    _log.info("proxmox_node_updated", name=name, address=address, by=user.login)
    return updated.model_dump(mode="json")


@router.delete("/proxmox/{name}", status_code=204)
async def delete_proxmox_node(
    name: str,
    user: UserInfo = Depends(require_admin),
) -> None:
    cfg = load_global()
    node = next((n for n in cfg.proxmox_nodes if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Proxmox node {name!r} not found")
    cfg.proxmox_nodes = [n for n in cfg.proxmox_nodes if n.name != name]
    save_global(cfg)
    Path(node.ssh_key_path).unlink(missing_ok=True)
    _log.info("proxmox_node_deleted", name=name, by=user.login)
