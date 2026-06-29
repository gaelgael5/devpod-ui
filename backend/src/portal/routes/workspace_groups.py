"""Routes /me/workspace-groups — groupes de workspaces utilisateur."""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db import workspace_groups as wg_db
from ..db.engine import get_conn

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["workspace-groups"])

_NAME_MAX = 50


class GroupCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty")
        if len(v) > _NAME_MAX:
            raise ValueError(f"name cannot exceed {_NAME_MAX} characters")
        return v


class GroupRenameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty")
        if len(v) > _NAME_MAX:
            raise ValueError(f"name cannot exceed {_NAME_MAX} characters")
        return v


class WorkspaceGroupsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groups: list[str]


@router.get("/workspace-groups")
async def list_workspace_groups(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await wg_db.list_groups(user.login, conn)


@router.post("/workspace-groups", status_code=201)
async def create_workspace_group(
    body: GroupCreateBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    try:
        group = await wg_db.create_group(user.login, body.name, conn)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if "uq_workspace_group_login_name" in str(exc):
            raise HTTPException(
                status_code=409, detail=f"Groupe '{body.name}' existe déjà"
            ) from exc
        raise
    _log.info("workspace_group_created", login=user.login, name=body.name)
    return group


@router.put("/workspace-groups/{group_id}")
async def rename_workspace_group(
    group_id: int,
    body: GroupRenameBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    try:
        result = await wg_db.rename_group(group_id, user.login, body.name, conn)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if "uq_workspace_group_login_name" in str(exc):
            raise HTTPException(
                status_code=409, detail=f"Groupe '{body.name}' existe déjà"
            ) from exc
        raise
    if result is None:
        raise HTTPException(status_code=404, detail="Groupe introuvable")
    _log.info("workspace_group_renamed", login=user.login, group_id=group_id, new_name=body.name)
    return result


@router.delete("/workspace-groups/{group_id}", status_code=204)
async def delete_workspace_group(
    group_id: int,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    deleted = await wg_db.delete_group(group_id, user.login, conn)
    if not deleted:
        raise HTTPException(status_code=404, detail="Groupe introuvable")
    _log.info("workspace_group_deleted", login=user.login, group_id=group_id)


@router.put("/workspaces/{workspace_name}/groups")
async def set_workspace_groups(
    workspace_name: str,
    body: WorkspaceGroupsBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    try:
        found = await wg_db.set_workspace_groups(
            user.login, workspace_name, body.groups, conn
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not found:
        raise HTTPException(status_code=404, detail="Workspace introuvable")
    _log.info(
        "workspace_groups_updated",
        login=user.login,
        workspace=workspace_name,
        groups=body.groups,
    )
    return {"workspace": workspace_name, "groups": body.groups}
