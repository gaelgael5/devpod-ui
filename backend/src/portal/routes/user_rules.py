"""Endpoints REST du bloc Rules : CRUD des règles + outils d'un service + test.

Règle v2 : événement déclencheur, conditions en ET (chacune = sonde MCP + test
sur le retour), actions ordonnées (service + méthode + args), enchaînement
optionnel vers une autre règle. POST /rules/{id}/test joue la règle (et sa
chaîne) immédiatement sur un événement synthétique et retourne les traces —
les actions s'exécutent réellement quand les conditions sont vraies.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..automation.engine import AutomationError, render_args
from ..automation.runtime import run_rule_chain
from ..automation.service_exec import call_service_primitive, list_service_tools
from ..db import user_rules as db
from ..db import user_services as services_db
from ..db.engine import get_conn
from ..events.models import EVENT_TYPES, AppEvent

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["rules"])


class RuleAction(BaseModel):
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


class RuleConditionBody(RuleAction):
    """Une sonde + son test — mêmes champs que l'action, plus la comparaison."""

    path: str = ""
    operator: Literal["eq", "neq", "contains", "not_contains"]
    value: str = ""


class RuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool = True
    event_type: str
    conditions: list[RuleConditionBody] = Field(default_factory=list)
    actions: list[RuleAction] = Field(min_length=1)
    next_rule_id: str | None = None

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
        "conditions": [c.model_dump() for c in body.conditions],
        "actions": [a.model_dump() for a in body.actions],
        "next_rule_id": body.next_rule_id,
    }


async def _require_valid_refs(
    conn: AsyncConnection, login: str, body: RuleBody, *, rule_id: str | None
) -> None:
    service_ids = {c.service_id for c in body.conditions} | {a.service_id for a in body.actions}
    for service_id in service_ids:
        if await services_db.get_service(conn, login, service_id) is None:
            raise HTTPException(status_code=422, detail=f"service introuvable: {service_id!r}")
    if body.next_rule_id is not None:
        if rule_id is not None and body.next_rule_id == rule_id:
            raise HTTPException(
                status_code=422, detail="une règle ne peut pas s'enchaîner sur elle-même"
            )
        if await db.get_rule(conn, login, body.next_rule_id) is None:
            raise HTTPException(
                status_code=422, detail=f"règle chaînée introuvable: {body.next_rule_id!r}"
            )


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
    await _require_valid_refs(conn, user.login, body, rule_id=None)
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
    await _require_valid_refs(conn, user.login, body, rule_id=rule_id)
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


class ServiceCallBody(BaseModel):
    """Essai direct d'un outil MCP (bouton « Tester » de l'éditeur de règles)."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    # Valeur injectée dans {workspace} pour cet essai.
    workspace: str | None = None

    @field_validator("tool")
    @classmethod
    def _tool_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("outil requis")
        return v


@router.post("/services/{service_id}/tools/call")
async def test_service_call_route(
    service_id: str,
    body: ServiceCallBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Appelle l'outil avec les args rendus et retourne le résultat brut.

    Endpoint de diagnostic : TOUTE erreur (gabarit, résolution, backend
    injoignable, outil en erreur) est retournée en clair, jamais avalée.
    """
    context = {
        "workspace": body.workspace or "",
        "actor": user.login,
        "event": "",
        "subject": {},
    }
    try:
        rendered = render_args(body.args, context)
        result = await call_service_primitive(user.login, service_id, body.tool, rendered)
    except Exception as exc:
        # Bouton d'essai : montrer l'échec est la fonction — pas un 500 opaque.
        _log.info(
            "service_tool_test_failed",
            service_id=service_id,
            tool=body.tool,
            login=user.login,
            error=f"{type(exc).__name__}: {exc}",
        )
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "args": rendered, "result": result}


@router.post("/rules/{rule_id}/test")
async def test_rule_route(
    rule_id: str,
    body: RuleTestBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Joue la règle (et sa chaîne) immédiatement et retourne les traces.

    Les actions sont RÉELLEMENT exécutées quand les conditions sont vraies (les
    règles sont des « ensure » idempotents : rejouer est sans danger).
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
        traces = await run_rule_chain(row, event, user.login)
    except AutomationError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "traces": traces}
