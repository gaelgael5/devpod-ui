"""Endpoints REST du bloc Rules : CRUD des règles + outils d'un service + test.

La règle est écrite par l'utilisateur : événement déclencheur, sonde (service +
outil MCP + args), condition (path/opérateur/valeur), action (service + outil +
args). POST /rules/{id}/test la joue immédiatement sur un événement synthétique
et retourne la trace complète (sonde, verdict, action) — l'action s'exécute
réellement si la condition est vraie.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..automation.engine import AutomationError, run_rule
from ..automation.runtime import rule_row_to_engine
from ..automation.service_exec import call_service_primitive, list_service_tools
from ..db import user_rules as db
from ..db import user_services as services_db
from ..db.engine import get_conn
from ..events.models import EVENT_TYPES, AppEvent

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["rules"])


class RulePrimitive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool")
    @classmethod
    def _tool_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("outil requis")
        return v


class RuleCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = ""
    operator: Literal["eq", "neq", "contains", "not_contains"]
    value: str = ""


class RuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool = True
    event_type: str
    probe: RulePrimitive
    condition: RuleCondition
    action: RulePrimitive

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("name requis, ≤ 100 caractères")
        return v

    @field_validator("event_type")
    @classmethod
    def _validate_event(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError(f"type d'événement inconnu: {v!r}")
        return v


class RuleTestBody(BaseModel):
    """Contexte de l'événement synthétique utilisé pour jouer la règle."""

    model_config = ConfigDict(extra="forbid")

    workspace: str | None = None
    subject: dict[str, Any] = Field(default_factory=dict)


def _db_fields(body: RuleBody) -> dict[str, Any]:
    return {
        "name": body.name,
        "enabled": body.enabled,
        "event_type": body.event_type,
        "probe_service_id": body.probe.service_id,
        "probe_tool": body.probe.tool,
        "probe_args": body.probe.args,
        "condition_path": body.condition.path,
        "condition_operator": body.condition.operator,
        "condition_value": body.condition.value,
        "action_service_id": body.action.service_id,
        "action_tool": body.action.tool,
        "action_args": body.action.args,
    }


async def _require_owned_services(conn: AsyncConnection, login: str, body: RuleBody) -> None:
    for service_id in {body.probe.service_id, body.action.service_id}:
        if await services_db.get_service(conn, login, service_id) is None:
            raise HTTPException(status_code=422, detail=f"service introuvable: {service_id!r}")


@router.get("/rules/events")
async def list_rule_events_route(user: UserInfo = Depends(require_user)) -> list[str]:
    """Types d'événements disponibles pour le déclencheur d'une règle."""
    return sorted(EVENT_TYPES)


@router.get("/rules")
async def list_rules_route(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await db.list_rules(conn, user.login)


@router.post("/rules", status_code=201)
async def create_rule_route(
    body: RuleBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    await _require_owned_services(conn, user.login, body)
    rule_id = await db.create_rule(conn, owner_login=user.login, **_db_fields(body))
    _log.info("rule_created", id=rule_id, name=body.name, login=user.login)
    return {"id": rule_id}


@router.put("/rules/{rule_id}")
async def update_rule_route(
    rule_id: str,
    body: RuleBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    await _require_owned_services(conn, user.login, body)
    if not await db.update_rule(conn, user.login, rule_id, **_db_fields(body)):
        raise HTTPException(status_code=404, detail="règle introuvable")
    return {"id": rule_id}


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule_route(
    rule_id: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await db.delete_rule(conn, user.login, rule_id):
        raise HTTPException(status_code=404, detail="règle introuvable")
    _log.info("rule_deleted", id=rule_id, login=user.login)


@router.get("/services/{service_id}/tools")
async def list_service_tools_route(
    service_id: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Outils MCP proposés par le profil du service (pour les selects de l'UI)."""
    try:
        prims = await list_service_tools(conn, user.login, service_id)
    except AutomationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        {
            "name": p.namespaced_name,
            "description": p.definition.get("description", ""),
            "input_schema": p.definition.get("inputSchema", {}),
        }
        for p in prims
    ]


@router.post("/rules/{rule_id}/test")
async def test_rule_route(
    rule_id: str,
    body: RuleTestBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Joue la règle immédiatement et retourne la trace complète.

    L'action est RÉELLEMENT exécutée si la condition est vraie (les règles sont
    des « ensure » idempotents : rejouer est sans danger).
    """
    row = await db.get_rule(conn, user.login, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="règle introuvable")
    event = AppEvent(
        type=row["event_type"],
        actor=user.login,
        workspace=body.workspace,
        subject=body.subject,
    )
    try:
        trace = await run_rule(rule_row_to_engine(row), event, call_service_primitive)
    except AutomationError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, **trace}
