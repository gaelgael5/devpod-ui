from __future__ import annotations

import re
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin, require_user
from ..db.engine import get_conn
from ..db.secrets import set_secret_public
from ..secrets.service import (
    SecretAlreadyExists,
    SecretNotFound,
    VaultLocked,
    edit_secret,
    list_user_secrets,
    list_user_secrets_by_type,
    register_secret,
    remove_secret,
    reveal_secret,
)

_log = structlog.get_logger(__name__)

router_me = APIRouter(tags=["secrets"])
router_admin = APIRouter(tags=["admin-secrets"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def _sid(request: Request) -> str:
    return str(request.session.get("session_id", ""))


def _handle_common(exc: Exception) -> None:
    if isinstance(exc, VaultLocked):
        raise HTTPException(status_code=403, detail="vault_locked") from exc
    if isinstance(exc, SecretAlreadyExists):
        raise HTTPException(status_code=409, detail="secret_already_exists") from exc
    if isinstance(exc, SecretNotFound):
        raise HTTPException(status_code=404, detail="secret_not_found") from exc


class RegisterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    description: str = ""
    secret_type: str
    secret_value: str
    storage_type: Literal["local", "harpocrate"] = "local"
    vault_identifier: str | None = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.fullmatch(v):
            raise ValueError("slug: alphanum minuscules + tirets/underscores")
        return v


class EditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    description: str = ""
    new_value: str | None = None


class VisibilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_public: bool


# ---------------------------------------------------------------------------
# Routes /me/secrets/...
# ---------------------------------------------------------------------------


@router_me.get("/secrets")
async def list_secrets_route(
    secret_type: str | None = Query(default=None),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    if secret_type is not None:
        return await list_user_secrets_by_type(user.login, secret_type, conn)
    return await list_user_secrets(user.login, conn)


@router_me.post("/secrets", status_code=201)
async def create_secret_route(
    body: RegisterBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        await register_secret(
            user.login,
            _sid(request),
            body.slug,
            body.label,
            body.description,
            body.secret_type,
            body.secret_value,
            storage_type=body.storage_type,
            vault_identifier=body.vault_identifier,
            conn=conn,
        )
    except Exception as exc:
        _handle_common(exc)
        raise
    return {"slug": body.slug}


@router_me.patch("/secrets/{slug}")
async def edit_secret_route(
    body: EditBody,
    request: Request,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        await edit_secret(
            user.login,
            _sid(request),
            slug,
            body.label,
            body.description,
            body.new_value,
            conn,
        )
    except Exception as exc:
        _handle_common(exc)
        raise
    return {"slug": slug}


@router_me.get("/secrets/{slug}/value")
async def get_secret_value_route(
    request: Request,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        value = await reveal_secret(user.login, _sid(request), slug, conn)
    except Exception as exc:
        _handle_common(exc)
        raise
    _log.info("secret_value_accessed", login=user.login, slug=slug)
    return {"secret_value": value}


@router_me.delete("/secrets/{slug}", status_code=204)
async def delete_secret_route(
    request: Request,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    try:
        await remove_secret(user.login, _sid(request), slug, conn)
    except Exception as exc:
        _handle_common(exc)
        raise


# ---------------------------------------------------------------------------
# Routes /admin/secrets/...
# ---------------------------------------------------------------------------


@router_admin.patch("/secrets/{owner_login}/{slug}/visibility")
async def set_secret_visibility(
    owner_login: str = Path(..., min_length=1, max_length=128),
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    body: VisibilityBody = Body(...),
    _user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    ok = await set_secret_public(owner_login, slug, body.is_public, conn)
    if not ok:
        raise HTTPException(status_code=404, detail="secret_not_found")
    return {"owner_login": owner_login, "slug": slug, "is_public": body.is_public}
