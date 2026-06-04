from __future__ import annotations

import os
import re
import shlex
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_user
from ..config.store import load_global
from ..devpod.env import UnknownHostError
from ..devpod.service import DevPodService

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["workspace-ops"])

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")


def _validate_name(name: str) -> None:
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid workspace name {name!r}: must match ^[a-z0-9][a-z0-9-]{{0,30}}[a-z0-9]$"
            ),
        )


class UpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    host: str = ""


_service: DevPodService | None = None


def _get_service() -> DevPodService:
    global _service
    if _service is None:
        _service = _build_service()
    return _service


def _build_service() -> DevPodService:
    import httpx

    from ..config.store import _data_root
    from ..exposure import ExposureService
    from ..exposure.caddy import CaddyClient
    from ..exposure.ports import PortRegistry

    global_cfg = load_global()
    # shlex.split with posix=False preserves Windows backslash paths intact.
    # On POSIX systems posix=True (default) would also work for single-token paths
    # like "/usr/local/bin/devpod"; using posix=False is safe for both platforms.
    devpod_bin = shlex.split(global_cfg.devpod.binary, posix=(os.name != "nt"))

    exposure: ExposureService | None = None
    if global_cfg.caddy.admin_api:
        data_root = _data_root()
        verify_uri = f"{global_cfg.server.external_url}/auth/caddy/verify"
        caddy = CaddyClient(
            admin_api=global_cfg.caddy.admin_api,
            http_client=httpx.AsyncClient(),
            verify_uri=verify_uri,
        )
        registry = PortRegistry(data_root)
        exposure = ExposureService(
            caddy=caddy,
            registry=registry,
            data_root=data_root,
            base_domain=global_cfg.server.base_domain,
        )

    return DevPodService(global_cfg=global_cfg, devpod_bin=devpod_bin, exposure=exposure)


def _reset_service() -> None:
    """Réinitialise le singleton du service (tests uniquement)."""
    global _service
    _service = None


@router.post("/workspaces/{name}/up", status_code=202)
async def workspace_up(
    name: str,
    req: UpRequest,
    user: UserInfo = Depends(require_user),
) -> dict[str, Any]:
    from ..config.models import WorkspaceSpec

    _validate_name(name)
    try:
        ws = WorkspaceSpec(name=name, source=req.source, host=req.host)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    svc = _get_service()
    try:
        ws_id = await svc.up(login=user.login, ws_spec=ws)
    except UnknownHostError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _log.info("workspace_up_requested", login=user.login, ws_id=ws_id)
    return {"ws_id": ws_id, "status": "provisioning"}


@router.post("/workspaces/{name}/stop")
async def workspace_stop(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, Any]:
    _validate_name(name)
    ws_id = f"{user.login}-{name}"
    svc = _get_service()
    await svc.stop(login=user.login, ws_id=ws_id)
    return {"ws_id": ws_id, "status": "stopped"}


@router.post("/workspaces/{name}/delete")
async def workspace_delete(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, Any]:
    _validate_name(name)
    ws_id = f"{user.login}-{name}"
    svc = _get_service()
    await svc.delete(login=user.login, ws_id=ws_id)
    return {"ws_id": ws_id, "deleted": True}


@router.get("/workspaces/{name}/status")
async def workspace_status(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, Any]:
    _validate_name(name)
    ws_id = f"{user.login}-{name}"
    svc = _get_service()
    return await svc.status(login=user.login, ws_id=ws_id)
