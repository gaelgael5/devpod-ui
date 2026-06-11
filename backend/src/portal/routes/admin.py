from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..auth.rbac import UserInfo, require_admin
from ..config.models import GlobalConfig, HostConfig
from ..config.store import _data_root, load_global, save_global

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])


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
        raise HTTPException(status_code=422, detail="Certificats TLS disponibles pour les hosts docker-tls uniquement")

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
