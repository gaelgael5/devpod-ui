"""Révélation du mot de passe console d'un host, gardée par le PIN vault.

Enabler 6e3d5f3a : le secret `host.{name}.ci-password` existe déjà (posé au
create/update du host) mais n'était consultable qu'en déchiffrant la base à la
main. Ici : une route dédiée, jamais de secret dans les réponses de liste,
validation du PIN (avec le lockout de `unlock_pin`) avant tout déchiffrement,
et chaque tentative — accordée ou refusée — tracée dans l'audit.
"""
from __future__ import annotations

import re

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..config.store import load_global
from ..db.engine import get_conn
from ..db.mcp_audit import record as _audit_record
from ..secrets.system import reveal_system_secret
from ..vault.pin import (
    PinLockedError,
    PinNotSetupError,
    PinWrongError,
    VaultDisabledError,
    unlock_pin,
)
from .vault import _sid

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])

_PIN_RE = re.compile(r"^\d{6}$")
_AUDIT_ACTION = "admin.host.ci_password.reveal"


class RevealCiPasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: str

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        if not _PIN_RE.fullmatch(v):
            raise ValueError("PIN must be exactly 6 digits")
        return v


async def _audit(
    conn: AsyncConnection, login: str, host: str, status: str, error: str | None
) -> None:
    await _audit_record(
        conn,
        apikey_id=None,
        owner_login=login,
        namespaced_name=_AUDIT_ACTION,
        backend_id=host,
        backend_key_id=None,
        latency_ms=None,
        status=status,
        error=error,
    )


@router.post("/hosts/{name}/ci-password/reveal")
async def reveal_host_ci_password(
    name: str,
    body: RevealCiPasswordBody,
    request: Request,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    """Renvoie le mot de passe console du host après validation du PIN.

    Le host est résolu AVANT la vérification du PIN : un nom inconnu ne doit
    pas consommer une tentative (le lockout protège le PIN, pas le routage).
    """
    cfg = load_global()
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")
    if not host.ci_password_secret_slug:
        raise HTTPException(
            status_code=404, detail=f"Host {name!r} has no console password"
        )

    try:
        await unlock_pin(user.login, body.pin, _sid(request), conn)
    except VaultDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PinLockedError as exc:
        await _audit(conn, user.login, name, "denied", "pin_locked")
        raise HTTPException(
            status_code=423,
            detail={
                "message": "PIN temporarily locked",
                "seconds_remaining": exc.seconds_remaining,
            },
        ) from exc
    except PinWrongError as exc:
        await _audit(conn, user.login, name, "denied", "pin_wrong")
        _log.warning("host_ci_password_reveal_denied", host=name, by=user.login)
        raise HTTPException(status_code=403, detail="Incorrect PIN") from exc
    except PinNotSetupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        value = await reveal_system_secret(host.ci_password_secret_slug, conn)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"Console password of {name!r} not stored"
        ) from exc

    await _audit(conn, user.login, name, "ok", None)
    _log.info("host_ci_password_revealed", host=name, by=user.login)
    return {"value": value}
