"""Lecture des messages workspace (API pour agents / MCP)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..config.store import load_user
from ..db.engine import get_conn
from ..messages import db as mdb
from ..messages.models import WorkspaceMessage

router = APIRouter(tags=["workspace-messages"])


@router.get("/workspaces/{ws}/messages")
async def list_workspace_messages(
    ws: str,
    limit: int = Query(default=50, ge=1, le=500),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[WorkspaceMessage]:
    """Messages contextuels du workspace (machines de test + services)."""
    user_cfg = await load_user(user.login)
    if not any(w.name == ws for w in user_cfg.workspaces):
        raise HTTPException(status_code=404, detail=f"Workspace {ws!r} introuvable")
    return await mdb.list_messages(conn, user.login, ws, limit=limit)
