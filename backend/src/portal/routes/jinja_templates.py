"""Admin CRUD des templates Jinja2 (clé × culture)."""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..db.engine import get_conn
from ..messages import db as mdb
from ..messages.models import Jinja2Template
from ..messages.renderer import render

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["jinja-templates"])

_RESERVED_HOST_KEY = "test_host_available"


class TemplateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str


class TemplatePreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str
    ctx: dict[str, Any] = {}


@router.get("/jinja-templates")
async def list_jinja_templates(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[Jinja2Template]:
    return await mdb.list_templates(conn)


@router.get("/jinja-templates/{key}/{culture}")
async def get_jinja_template(
    key: str,
    culture: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> Jinja2Template:
    body = await mdb.get_template(conn, key, culture)
    if body is None:
        raise HTTPException(status_code=404, detail=f"Template {key!r}/{culture!r} introuvable")
    return Jinja2Template(key=key, culture=culture, body=body)


@router.put("/jinja-templates/{key}/{culture}", status_code=200)
async def upsert_jinja_template(
    key: str,
    culture: str,
    body: TemplateBody,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> Jinja2Template:
    tpl = Jinja2Template(key=key, culture=culture, body=body.body)
    await mdb.upsert_template(conn, tpl)
    _log.info("jinja2_template_saved", key=key, culture=culture, by=user.login)
    return tpl


@router.delete("/jinja-templates/{key}/{culture}", status_code=204)
async def delete_jinja_template(
    key: str,
    culture: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    await mdb.delete_template(conn, key, culture)
    _log.info("jinja2_template_deleted", key=key, culture=culture, by=user.login)


@router.post("/jinja-templates/preview")
async def preview_jinja_template(
    body: TemplatePreviewBody,
    user: UserInfo = Depends(require_admin),
) -> dict[str, str]:
    """Rend un template Jinja2 avec un contexte de test fourni par l'admin."""
    try:
        rendered = render(body.body, body.ctx)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"rendered": rendered}
