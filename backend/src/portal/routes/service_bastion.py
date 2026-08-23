"""Endpoints service du provisioning bastion↔Termix (connecteur par automates).

Cibles d'appel des automates (events `workspace.*` du journal `app_event`), sous
clé API admin (`require_admin_or_api_key`), audités. Statuts honnêtes pour que le
run de l'automate reflète la réalité : 200 fait, 409 config bastion incomplète,
422 entrée invalide, 502 échec Termix — un run `failed` se rejoue depuis l'écran
automates une fois la cause corrigée.
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_admin_or_api_key
from ..bastion.provision import (
    BastionNotConfiguredError,
    deprovision_workspace,
    provision_workspace,
)
from ..db.engine import _get_engine
from ..db.mcp_audit import record as audit_record

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["service-bastion"])

_Caller = Annotated[UserInfo, Depends(require_admin_or_api_key)]


class BastionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str
    ws_id: str


async def _audit(
    actor: str, action: str, target: str, status: str, error: str | None = None
) -> None:
    async with _get_engine().begin() as conn:
        await audit_record(
            conn,
            apikey_id=None,
            owner_login=actor,
            namespaced_name=action,
            backend_id=target,
            backend_key_id=None,
            latency_ms=None,
            status=status,
            error=error,
        )


async def _call(op: str, fn: Any, body: BastionTarget, caller: UserInfo) -> dict[str, Any]:
    action = f"service.bastion.{op}"
    try:
        result: dict[str, Any] = await fn(body.login, body.ws_id)
    except BastionNotConfiguredError as exc:
        await _audit(caller.login, action, body.ws_id, "denied", str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        await _audit(caller.login, action, body.ws_id, "denied", str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception as exc:
        _log.warning("bastion_service_failed", op=op, ws_id=body.ws_id, exc_info=True)
        await _audit(caller.login, action, body.ws_id, "error", str(exc))
        raise HTTPException(status_code=502, detail=f"{op} bastion/Termix : {exc}") from None
    await _audit(caller.login, action, body.ws_id, "ok")
    return result


@router.post("/bastion/provision")
async def provision_bastion(body: BastionTarget, caller: _Caller) -> dict[str, Any]:
    """Provisionne (idempotent) l'accès Termix d'un workspace."""
    return await _call("provision", provision_workspace, body, caller)


@router.post("/bastion/deprovision")
async def deprovision_bastion(body: BastionTarget, caller: _Caller) -> dict[str, Any]:
    """Retire l'accès Termix d'un workspace (idempotent, 404 Termix tolérés)."""
    return await _call("deprovision", deprovision_workspace, body, caller)
