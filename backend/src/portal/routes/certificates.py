from __future__ import annotations

import re
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin, require_user
from ..certificates.service import (
    CertAlreadyExists,
    CertNotFound,
    VaultLocked,
    generate_and_register,
    list_user_certificates,
    register_certificate,
    remove_certificate,
    reveal_private_key,
)
from ..db.certificates import set_public
from ..db.engine import get_conn

_log = structlog.get_logger(__name__)

router_me = APIRouter(tags=["certificates"])
router_admin = APIRouter(tags=["admin-certificates"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

CERT_TYPES = Literal[
    "ssh-ed25519",
    "ssh-rsa-2048",
    "ssh-rsa-4096",
    "ssh-ecdsa-p256",
    "tls-rsa-2048",
    "tls-rsa-4096",
    "tls-ec-p256",
    "tls-ec-p384",
]


def _sid(request: Request) -> str:
    return str(request.session.get("session_id", ""))


def _handle_common(exc: Exception) -> None:
    if isinstance(exc, VaultLocked):
        raise HTTPException(status_code=403, detail="vault_locked") from exc
    if isinstance(exc, CertAlreadyExists):
        raise HTTPException(status_code=409, detail="cert_already_exists") from exc
    if isinstance(exc, CertNotFound):
        raise HTTPException(status_code=404, detail="cert_not_found") from exc


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    description: str = ""
    cert_type: CERT_TYPES
    storage_type: Literal["local", "harpocrate"] = "local"
    vault_identifier: str | None = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.fullmatch(v):
            raise ValueError("slug: lowercase alphanum + tirets/underscores, 1-63 chars")
        return v


class RegisterBody(GenerateBody):
    public_key: str
    private_key_pem: str


class VisibilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_public: bool


# ---------------------------------------------------------------------------
# Routes /me/certificates/...
# ---------------------------------------------------------------------------


@router_me.get("/certificates")
async def list_certs(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await list_user_certificates(user.login, conn)


@router_me.post("/certificates/generate")
async def generate_cert(
    body: GenerateBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        pub = await generate_and_register(
            user.login,
            _sid(request),
            body.slug,
            body.label,
            body.description,
            body.cert_type,
            storage_type=body.storage_type,
            vault_identifier=body.vault_identifier,
            conn=conn,
        )
    except Exception as exc:
        _handle_common(exc)
        raise
    return {"public_key": pub, "slug": body.slug}


@router_me.post("/certificates")
async def register_cert(
    body: RegisterBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        await register_certificate(
            user.login,
            _sid(request),
            body.slug,
            body.label,
            body.description,
            body.cert_type,
            body.public_key,
            body.private_key_pem,
            storage_type=body.storage_type,
            vault_identifier=body.vault_identifier,
            conn=conn,
        )
    except Exception as exc:
        _handle_common(exc)
        raise
    return {"slug": body.slug}


@router_me.get("/certificates/{slug}/private")
async def get_private(
    request: Request,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        pem = await reveal_private_key(user.login, _sid(request), slug, conn)
    except Exception as exc:
        _handle_common(exc)
        raise
    _log.info("certificate_private_key_accessed", login=user.login, slug=slug)
    return {"private_key_pem": pem}


@router_me.delete("/certificates/{slug}", status_code=204)
async def delete_cert(
    request: Request,
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    try:
        await remove_certificate(user.login, _sid(request), slug, conn)
    except Exception as exc:
        _handle_common(exc)
        raise


# ---------------------------------------------------------------------------
# Routes /admin/certificates/...
# ---------------------------------------------------------------------------


@router_admin.patch("/certificates/{slug}/visibility")
async def set_visibility(
    slug: str = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$"),
    body: VisibilityBody = Body(...),
    _user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    ok = await set_public(slug, body.is_public, conn)
    if not ok:
        raise HTTPException(status_code=404, detail="cert_not_found")
    return {"slug": slug, "is_public": body.is_public}
