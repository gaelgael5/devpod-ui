"""Routes /api/compose : templates (admin) + déploiements (dev)."""
from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin, require_user
from ..compose import db as cdb
from ..compose import service as csvc
from ..compose.models import ComposeDeployment, ComposeTemplate, validate_slug
from ..compose.ports import PortConflict
from ..compose.service import ComposeServiceError
from ..compose.validation import TemplateValidationError, validate_template
from ..config.models import HostConfig
from ..config.store import load_global, load_user
from ..db.engine import get_conn
from ..db.test_hosts import host_full_info
from ..schemas.compose import DeploymentCreateBody, TemplateCreateBody, TemplateUpdateBody
from ..settings import get_settings

_log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/compose", tags=["compose"])


@router.get("/templates")
async def list_templates(
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
    tag: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    return [t.model_dump(mode="json") for t in await cdb.list_templates(conn, tag)]


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict[str, Any]:
    tpl = await cdb.get_template(conn, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="template inconnu")
    return tpl.model_dump(mode="json")


@router.post("/templates", status_code=201)
async def create_template(
    body: TemplateCreateBody,
    user: Annotated[UserInfo, Depends(require_admin)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict[str, Any]:
    try:
        validate_slug(body.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if await cdb.get_template(conn, body.id) is not None:
        raise HTTPException(status_code=409, detail=f"template {body.id!r} existe déjà")
    try:
        warnings = validate_template(body.compose_content, body.parameters)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tpl = ComposeTemplate(**body.model_dump())
    await cdb.create_template(conn, tpl)
    return {"template": tpl.model_dump(mode="json"), "warnings": warnings}


@router.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    body: TemplateUpdateBody,
    user: Annotated[UserInfo, Depends(require_admin)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict[str, Any]:
    if await cdb.get_template(conn, template_id) is None:
        raise HTTPException(status_code=404, detail="template inconnu")
    try:
        warnings = validate_template(body.compose_content, body.parameters)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tpl = ComposeTemplate(id=template_id, **body.model_dump())
    await cdb.update_template(conn, tpl)
    return {"template": tpl.model_dump(mode="json"), "warnings": warnings}


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: str,
    user: Annotated[UserInfo, Depends(require_admin)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> None:
    count = await cdb.count_deployments_for_template(conn, template_id)
    if count > 0:
        raise HTTPException(status_code=409, detail="template référencé par des déploiements")
    await cdb.delete_template(conn, template_id)


# ---------------------------------------------------------------------------
# Helpers ownership
# ---------------------------------------------------------------------------

def _is_admin(user: UserInfo) -> bool:
    return get_settings().oidc_admin_role in user.roles


def _eligible_hosts(hosts: list[HostConfig]) -> list[HostConfig]:
    return [h for h in hosts if h.type == "ssh"]


async def _require_owned(
    conn: AsyncConnection, deployment_id: str, user: UserInfo
) -> ComposeDeployment:
    dep = await cdb.get_deployment(conn, deployment_id)
    if dep is None:
        raise HTTPException(status_code=404, detail="déploiement inconnu")
    if dep.owner_login != user.login and not _is_admin(user):
        raise HTTPException(status_code=403, detail="déploiement d'un autre utilisateur")
    return dep


# ---------------------------------------------------------------------------
# Routes nodes (for deployment node selection)
# ---------------------------------------------------------------------------

@router.get("/nodes")
async def list_nodes(
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> list[dict[str, Any]]:
    hosts = _eligible_hosts(load_global().hosts)
    result: list[dict[str, Any]] = []
    for h in hosts:
        usage = h.usage or "workspaces"
        entry: dict[str, Any] = {"node_id": h.name, "name": h.name, "usage": usage}
        if h.usage == "tests":
            info = await host_full_info(h.name, conn)
            if info:
                entry["owner_login"] = info[0]
                entry["workspace_name"] = info[1]
                entry["alias"] = info[2]
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Routes déploiements (dev + ownership)
# ---------------------------------------------------------------------------

@router.get("/deployments")
async def list_deployments(
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> list[dict[str, Any]]:
    owner = None if _is_admin(user) else user.login
    deps = await cdb.list_deployments(conn, owner_login=owner)
    return [d.model_dump(mode="json") for d in deps]


@router.post("/deployments", status_code=201)
async def create_deployment(
    body: DeploymentCreateBody,
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict[str, Any]:
    try:
        validate_slug(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tpl = await cdb.get_template(conn, body.template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="template inconnu")
    missing = [p.key for p in tpl.parameters if p.required and p.key not in body.env_values]
    if missing:
        raise HTTPException(status_code=422, detail=f"paramètres requis manquants: {missing}")
    if await cdb.get_deployment_by_name_node(conn, body.name, body.node_id) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"déploiement {body.name!r} existe déjà sur ce nœud",
        )
    user_cfg = await load_user(user.login)
    try:
        dep = await csvc.deploy(
            conn,
            name=body.name,
            template=tpl,
            node_id=body.node_id,
            owner_login=user.login,
            secret_ns=user_cfg.secret_ns,
            env_values=body.env_values,
        )
    except PortConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "port_conflict",
                "conflicts": sorted(exc.conflicts),
                "suggestion": exc.suggestion,
            },
        ) from exc
    except ComposeServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return dep.model_dump(mode="json")


@router.post("/deployments/{deployment_id}/{action}")
async def deployment_action(
    deployment_id: str,
    action: str,
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict[str, Any]:
    if action not in ("stop", "start", "restart"):
        raise HTTPException(status_code=422, detail="action invalide")
    await _require_owned(conn, deployment_id, user)
    try:
        await csvc.lifecycle(conn, deployment_id, action)  # type: ignore[arg-type]
    except ComposeServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"deployment_id": deployment_id, "action": action}


@router.delete("/deployments/{deployment_id}", status_code=204)
async def delete_deployment(
    deployment_id: str,
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> None:
    await _require_owned(conn, deployment_id, user)
    await csvc.teardown(conn, deployment_id)


@router.get("/deployments/{deployment_id}/logs")
async def deployment_logs(
    deployment_id: str,
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
    service: str | None = Query(default=None),
    tail: int = Query(default=200, ge=1, le=5000),
) -> dict[str, Any]:
    await _require_owned(conn, deployment_id, user)
    return {"output": await csvc.fetch_logs(conn, deployment_id, service=service, tail=tail)}


@router.get("/deployments/{deployment_id}/status")
async def deployment_status(
    deployment_id: str,
    user: Annotated[UserInfo, Depends(require_user)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> dict[str, Any]:
    await _require_owned(conn, deployment_id, user)
    status = await csvc.refresh_status(conn, deployment_id)
    return {"deployment_id": deployment_id, "status": status}
