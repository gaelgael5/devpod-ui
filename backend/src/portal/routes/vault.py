from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db.engine import get_conn
from ..vault.keys import (
    KeyAlreadyExists,
    KeyNotFound,
    VaultLocked,
    add_key,
    delete_key,
    list_keys,
    test_key_connection,
)
from ..vault.pin import (
    PinLockedError,
    PinNotSetupError,
    PinSetupResult,
    PinWrongError,
    VaultDisabledError,
    get_vault_status,
    recover_pin,
    reset_vault,
    setup_pin,
    unlock_pin,
)

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["vault"])

_PIN_RE = re.compile(r"^\d{6}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")


def _sid(request: Request) -> str:
    return str(request.session.get("session_id", ""))


class PinBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: str

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        if not _PIN_RE.fullmatch(v):
            raise ValueError("PIN must be exactly 6 digits")
        return v


class RecoverBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recovery_code: str
    new_pin: str

    @field_validator("new_pin")
    @classmethod
    def validate_new_pin(cls, v: str) -> str:
        if not _PIN_RE.fullmatch(v):
            raise ValueError("new_pin must be exactly 6 digits")
        return v


class AddKeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identifier: str
    token: str
    url: str
    description: str = ""

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, v: str) -> str:
        if not _ID_RE.fullmatch(v):
            raise ValueError("identifier: lowercase alphanum + hyphens/underscores")
        return v

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        if not v.startswith("hrpv_"):
            raise ValueError("token must start with 'hrpv_'")
        return v


@router.get("/vault/status")
async def vault_status(
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    status = await get_vault_status(user.login, _sid(request), conn)
    return {"status": status}


@router.post("/vault/pin/setup")
async def pin_setup(
    body: PinBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        result: PinSetupResult = await setup_pin(user.login, body.pin, _sid(request), conn)
    except VaultDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"recovery_code": result.recovery_code}


@router.post("/vault/pin/unlock")
async def pin_unlock(
    body: PinBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        await unlock_pin(user.login, body.pin, _sid(request), conn)
    except VaultDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PinLockedError as exc:
        raise HTTPException(
            status_code=423,
            detail={
                "message": "PIN temporarily locked",
                "seconds_remaining": exc.seconds_remaining,
            },
        ) from exc
    except PinWrongError as exc:
        raise HTTPException(status_code=403, detail="Incorrect PIN") from exc
    except PinNotSetupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "unlocked"}


@router.post("/vault/pin/recover")
async def pin_recover(
    body: RecoverBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        result = await recover_pin(
            user.login, body.recovery_code, body.new_pin, _sid(request), conn
        )
    except VaultDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PinWrongError as exc:
        raise HTTPException(status_code=403, detail="Incorrect recovery code") from exc
    except PinNotSetupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"recovery_code": result.recovery_code}


@router.delete("/vault/pin", status_code=204)
async def pin_reset(
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    await reset_vault(user.login, _sid(request), conn)


@router.get("/vault/keys")
async def vault_list_keys(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await list_keys(user.login, conn)


@router.post("/vault/keys")
async def vault_add_key(
    body: AddKeyBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        await add_key(
            user.login,
            _sid(request),
            body.identifier,
            body.token,
            body.url,
            body.description,
            conn,
        )
    except VaultLocked as exc:
        raise HTTPException(status_code=403, detail="vault_locked") from exc
    except KeyAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"identifier": body.identifier}


@router.delete("/vault/keys/{identifier}", status_code=204)
async def vault_delete_key(
    identifier: str,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    try:
        await delete_key(user.login, _sid(request), identifier, conn)
    except VaultLocked as exc:
        raise HTTPException(status_code=403, detail="vault_locked") from exc
    except KeyNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/vault/keys/{identifier}/test")
async def vault_test_key(
    identifier: str,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    _log.info("vault_key_test_requested", identifier=identifier, login=user.login)
    try:
        result = await test_key_connection(user.login, _sid(request), identifier, conn)
        _log.info("vault_key_tested", identifier=identifier, login=user.login)
        return result
    except VaultLocked as exc:
        raise HTTPException(status_code=403, detail="vault_locked") from exc
    except KeyNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _log.warning(
            "vault_key_test_failed",
            identifier=identifier,
            login=user.login,
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail="key_test_failed") from exc
