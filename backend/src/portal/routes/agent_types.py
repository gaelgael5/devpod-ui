"""Routes des types d'agents workspace (spec 35 §5.2).

CRUD admin (la table est globale), liste réduite côté user pour le formulaire
de création de workspace, prévisualisation du template avec un contexte factice
(jamais de vrai token).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..agents.models import AgentTypeCreate, AgentTypeUpdate
from ..agents.renderer import AgentRenderError, build_render_context, render_agent_file
from ..agents.resync import resync_agent_type_workspaces
from ..auth.rbac import UserInfo, require_admin, require_user
from ..db import agent_types as db
from ..db.engine import get_conn
from ..db.tables import workspaces

_log = structlog.get_logger(__name__)

admin_router = APIRouter(tags=["agent-types"])
me_router = APIRouter(tags=["agent-types"])

_AgentId = Annotated[str, Path(pattern=r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")]


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: str


def _preview_context() -> dict[str, Any]:
    """Contexte factice pour l'éditeur : tokens d'exemple, jamais de vraie clef."""
    from ..agents.keys import WorkspaceKey

    return build_render_context(
        keys=[
            WorkspaceKey("k1", "p1", "défaut", "mcpk_EXEMPLE_xxxxxxxxxxxxxxxx"),
            WorkspaceKey("k2", "p2", "lecture seule", "mcpk_EXEMPLE_yyyyyyyyyyyyyyyy"),
        ],
        mcp_url="https://portal.example.org/mcp/",
        ws_id="alice-mon-ws",
        workspace_name="mon-ws",
        owner_login="alice",
        home="$HOME",
        project_root="/workspaces/alice-mon-ws",
    )


async def _workspaces_using(conn: AsyncConnection, agent_id: str) -> list[str]:
    q = select(workspaces.c.login, workspaces.c.name).where(workspaces.c.agents.any(agent_id))
    return [f"{r.login}-{r.name}" for r in (await conn.execute(q)).all()]


# ─── Admin ────────────────────────────────────────────────────────────────────


@admin_router.get("/agent-types")
async def list_agent_types_route(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await db.list_agent_types(conn)


@admin_router.post("/agent-types", status_code=201)
async def create_agent_type_route(
    body: AgentTypeCreate,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    try:
        # SAVEPOINT : un doublon ne doit pas avorter la transaction de la requête
        # (la réponse 409 partirait d'une transaction empoisonnée).
        async with conn.begin_nested():
            await db.insert_agent_type(
                conn,
                id=body.id,
                label=body.label,
                filename=body.filename,
                template=body.template,
                target_path=body.target_path,
                mode=body.mode,
                enabled=body.enabled,
            )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"type '{body.id}' déjà défini") from exc
    _log.info("agent_type_created", agent_id=body.id, login=user.login)
    return {"id": body.id}


@admin_router.patch("/agent-types/{agent_id}")
async def update_agent_type_route(
    body: AgentTypeUpdate,
    agent_id: _AgentId,
    user: UserInfo = Depends(require_admin),
) -> dict[str, str]:
    # Transaction dédiée committée AVANT le resync — cf. set_profile_exposed_route :
    # l'ordre commit/BackgroundTasks n'est pas garanti, le resync doit lire le
    # template à jour.
    from ..db.engine import _get_engine

    async with _get_engine().begin() as conn:
        if not await db.update_agent_type(
            conn,
            agent_id,
            label=body.label,
            filename=body.filename,
            template=body.template,
            target_path=body.target_path,
            enabled=body.enabled,
            mode=body.mode,
        ):
            raise HTTPException(status_code=404, detail="type d'agent introuvable")
    _spawn_agent_type_resync(agent_id)
    _log.info("agent_type_updated", agent_id=agent_id, login=user.login)
    return {"id": agent_id}


# Références fortes sur les resyncs fire-and-forget (sinon GC possible mi-course).
_resync_tasks: set[asyncio.Task[Any]] = set()


def _spawn_agent_type_resync(agent_id: str) -> None:
    task = asyncio.create_task(resync_agent_type_workspaces(agent_id))
    _resync_tasks.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _resync_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            _log.error("agent_resync_task_failed", agent_id=agent_id, exc_info=t.exception())

    task.add_done_callback(_done)


@admin_router.delete("/agent-types/{agent_id}", status_code=204)
async def delete_agent_type_route(
    agent_id: _AgentId,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    used_by = await _workspaces_using(conn, agent_id)
    if used_by:
        raise HTTPException(
            status_code=409,
            detail=f"type utilisé par {len(used_by)} workspace(s) : {', '.join(sorted(used_by))}",
        )
    if not await db.delete_agent_type(conn, agent_id):
        raise HTTPException(status_code=404, detail="type d'agent introuvable")
    _log.info("agent_type_deleted", agent_id=agent_id, login=user.login)


@admin_router.post("/agent-types/{agent_id}/preview")
async def preview_agent_type_route(
    body: PreviewRequest,
    agent_id: _AgentId,
    user: UserInfo = Depends(require_admin),
) -> dict[str, str]:
    """Rendu du template de l'éditeur (non sauvegardé) avec un contexte factice."""
    try:
        content = render_agent_file(body.template, _preview_context())
    except AgentRenderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"content": content}


# ─── Utilisateur ──────────────────────────────────────────────────────────────


@me_router.get("/agent-types")
async def list_enabled_agent_types_route(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, str]]:
    rows = await db.list_agent_types(conn, enabled_only=True)
    return [{"id": r["id"], "label": r["label"]} for r in rows]
