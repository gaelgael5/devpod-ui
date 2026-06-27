"""Routes /api/compose : templates (admin) + déploiements (dev)."""
from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..compose import db as cdb
from ..compose.models import ComposeTemplate, validate_slug
from ..compose.validation import TemplateValidationError, validate_template
from ..db.engine import get_conn
from ..schemas.compose import TemplateCreateBody, TemplateUpdateBody

_log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/compose", tags=["compose"])


@router.get("/templates")
async def list_templates(
    user: Annotated[UserInfo, Depends(require_admin)],
    conn: Annotated[AsyncConnection, Depends(get_conn)],
    tag: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    return [t.model_dump(mode="json") for t in await cdb.list_templates(conn, tag)]


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    user: Annotated[UserInfo, Depends(require_admin)],
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
    await cdb.delete_template(conn, template_id)
