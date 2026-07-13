"""Kiosque d'applications — `GET/POST /me/applications`, `DELETE /me/applications/{id}`.

Liens personnels (icône + nom + URL) affichés sur la page Applications. L'URL
est restreinte à http(s) — un lien `javascript:` stocké puis rendu dans un
<a href> serait un XSS stocké. L'icône est un emoji/texte court ou une URL
d'image https (même restriction de schéma).
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db.engine import get_conn
from ..db.user_applications import add_application, delete_application, list_applications
from ..db.user_config import ensure_user_db

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["applications"])

_ALLOWED_SCHEMES = ("http://", "https://")


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    icon: str = ""

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 60:
            raise ValueError("name must be 1-60 characters")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 2000 or not v.lower().startswith(_ALLOWED_SCHEMES):
            raise ValueError("url must start with http:// or https:// (max 2000 chars)")
        return v

    @field_validator("icon")
    @classmethod
    def _icon(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 300:
            raise ValueError("icon must be ≤ 300 characters")
        # Une icône « URL » doit être http(s) ; sinon c'est un emoji/texte court.
        if "://" in v and not v.lower().startswith(_ALLOWED_SCHEMES):
            raise ValueError("icon url must start with http:// or https://")
        return v


@router.get("/applications")
async def get_applications(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await list_applications(user.login, conn)


@router.post("/applications", status_code=201)
async def post_application(
    body: ApplicationCreate,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    # Garde-FK : garantit la ligne users avant l'insert (idempotent).
    await ensure_user_db(user.login, conn)
    try:
        row = await add_application(user.login, body.name, body.url, body.icon, conn)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail=f"application {body.name!r} already exists"
        ) from exc
    _log.info("application_added", login=user.login, name=body.name)
    return row


@router.delete("/applications/{app_id}", status_code=204)
async def remove_application(
    app_id: int,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await delete_application(user.login, app_id, conn):
        raise HTTPException(status_code=404, detail="application not found")
    _log.info("application_deleted", login=user.login, app_id=app_id)
