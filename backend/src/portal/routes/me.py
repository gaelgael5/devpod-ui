from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..auth.rbac import UserInfo, require_user
from ..config.models import UserConfig, WorkspaceSpec
from ..config.store import load_user, save_user
from ..devpod.git import run_git_ls_remote

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["me"])


@router.get("")
async def get_current_user(user: UserInfo = Depends(require_user)) -> dict[str, object]:
    return {"login": user.login, "roles": user.roles}


@router.get("/config")
async def get_config(user: UserInfo = Depends(require_user)) -> dict[str, object]:
    cfg = load_user(user.login)
    return cfg.model_dump(mode="json")


@router.put("/config")
async def put_config(
    updates: dict[str, object], user: UserInfo = Depends(require_user)
) -> dict[str, object]:
    cfg = load_user(user.login)
    merged = cfg.model_dump(mode="json")
    merged.update(updates)
    try:
        new_cfg = UserConfig.model_validate(merged)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    save_user(user.login, new_cfg)
    _log.info("user_config_updated", login=user.login)
    return new_cfg.model_dump(mode="json")


@router.get("/workspaces")
async def list_workspaces(user: UserInfo = Depends(require_user)) -> list[dict[str, object]]:
    cfg = load_user(user.login)
    return [ws.model_dump(mode="json") for ws in cfg.workspaces]


@router.post("/workspaces", status_code=201)
async def add_workspace(
    workspace: WorkspaceSpec, user: UserInfo = Depends(require_user)
) -> dict[str, object]:
    cfg = load_user(user.login)
    if any(ws.name == workspace.name for ws in cfg.workspaces):
        raise HTTPException(status_code=409, detail=f"Workspace {workspace.name!r} already exists")
    cfg.workspaces.append(workspace)
    save_user(user.login, cfg)
    _log.info("workspace_added", login=user.login, name=workspace.name)
    return workspace.model_dump(mode="json")


@router.get("/git/branches")
async def list_git_branches(
    url: str,
    credential: str = "",
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    """Retourne les branches d'un dépôt git distant via git ls-remote."""
    returncode, stdout, _ = await run_git_ls_remote(url, credential, user.login)

    if returncode != 0:
        raise HTTPException(
            status_code=422, detail="Cannot list branches (check URL and credentials)"
        )

    branches: list[str] = []
    default: str | None = None
    for line in stdout.decode(errors="replace").splitlines():
        if line.startswith("ref: refs/heads/") and "\t" in line:
            default = line.split("\t")[0][len("ref: refs/heads/"):]
        elif "\trefs/heads/" in line:
            branches.append(line.split("\t")[1][len("refs/heads/"):])

    if default and default in branches:
        branches.remove(default)
        branches.insert(0, default)

    _log.info("git_branches_listed", login=user.login, url=url, count=len(branches))
    return {"branches": branches, "default": default}


@router.get("/git-credentials")
async def list_git_credentials(
    user: UserInfo = Depends(require_user),
) -> list[dict[str, object]]:
    cfg = load_user(user.login)
    return [
        {"name": c.name, "host": c.host, "kind": c.kind}
        for c in cfg.git_credentials
    ]


@router.delete("/workspaces/{name}")
async def delete_workspace(name: str, user: UserInfo = Depends(require_user)) -> dict[str, object]:
    cfg = load_user(user.login)
    before = len(cfg.workspaces)
    cfg.workspaces = [ws for ws in cfg.workspaces if ws.name != name]
    if len(cfg.workspaces) == before:
        raise HTTPException(status_code=404, detail=f"Workspace {name!r} not found")
    save_user(user.login, cfg)
    _log.info("workspace_deleted", login=user.login, name=name)
    return {"deleted": name}
