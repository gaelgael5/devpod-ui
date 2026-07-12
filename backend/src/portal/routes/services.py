"""Endpoints REST du registre de services (hub Services & Security).

CRUD simple v1 : nom, URL, profil MCP d'accès. Comportements additionnels
(exécution, health-check, etc.) hors périmètre — à spécifier ultérieurement.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db import mcp_profiles as profiles_db
from ..db import user_services as db
from ..db.engine import get_conn

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["services"])


class ServiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    # Requis fonctionnellement (le profil est ce qui donne accès au service),
    # mais nullable en DB : un profil supprimé après coup ne doit pas invalider
    # la ligne existante (SET NULL) — seule la création/mise à jour l'exige.
    mcp_profile_id: str

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("name requis, ≤ 100 caractères")
        return v

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"URL http(s) absolue requise: {v!r}")
        return v


async def _require_owned_profile(conn: AsyncConnection, owner_login: str, profile_id: str) -> None:
    if await profiles_db.get_profile(conn, owner_login, profile_id) is None:
        raise HTTPException(status_code=422, detail="profil MCP introuvable")


@router.get("/services")
async def list_services_route(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await db.list_services(conn, user.login)


@router.post("/services", status_code=201)
async def create_service_route(
    body: ServiceBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    await _require_owned_profile(conn, user.login, body.mcp_profile_id)
    sid = await db.create_service(
        conn,
        owner_login=user.login,
        name=body.name,
        url=body.url,
        mcp_profile_id=body.mcp_profile_id,
    )
    _log.info("service_created", id=sid, name=body.name, login=user.login)
    return {"id": sid}


@router.put("/services/{service_id}")
async def update_service_route(
    service_id: str,
    body: ServiceBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    await _require_owned_profile(conn, user.login, body.mcp_profile_id)
    ok = await db.update_service(
        conn,
        user.login,
        service_id,
        name=body.name,
        url=body.url,
        mcp_profile_id=body.mcp_profile_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="service introuvable")
    return {"id": service_id}


@router.delete("/services/{service_id}", status_code=204)
async def delete_service_route(
    service_id: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await db.delete_service(conn, user.login, service_id):
        raise HTTPException(status_code=404, detail="service introuvable")
    _log.info("service_deleted", id=service_id, login=user.login)
