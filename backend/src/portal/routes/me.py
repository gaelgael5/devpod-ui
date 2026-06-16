from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_user
from ..config.models import GitCredential, UserConfig, WorkspaceSpec
from ..config.store import load_user, safe_user_path, save_user
from ..devpod.git import run_git_ls_remote

_CRED_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}[a-z0-9]$")

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
    returncode, stdout, stderr = await run_git_ls_remote(url, credential, user.login)

    if returncode != 0:
        err = stderr.decode(errors="replace").strip() if stderr else ""
        _log.warning(
            "git_ls_remote_failed",
            login=user.login,
            url=url,
            returncode=returncode,
            stderr=err,
        )
        raise HTTPException(
            status_code=422,
            detail=err or "git ls-remote a échoué",
        )

    branches: list[str] = []
    default: str | None = None
    for line in stdout.decode(errors="replace").splitlines():
        if line.startswith("ref: refs/heads/") and "\t" in line:
            default = line.split("\t")[0][len("ref: refs/heads/") :]
        elif "\trefs/heads/" in line:
            branches.append(line.split("\t")[1][len("refs/heads/") :])

    if default and default in branches:
        branches.remove(default)
        branches.insert(0, default)

    _log.info("git_branches_listed", login=user.login, url=url, count=len(branches))
    return {"branches": branches, "default": default}


class _GitCredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    host: str
    kind: Literal["ssh", "token"]
    username: str = ""
    token: str = ""
    private_key: str = ""


@router.get("/git-credentials")
async def list_git_credentials(
    user: UserInfo = Depends(require_user),
) -> list[dict[str, object]]:
    cfg = load_user(user.login)
    return [
        {"name": c.name, "host": c.host, "kind": c.kind, "username": c.username}
        for c in cfg.git_credentials
    ]


@router.post("/git-credentials", status_code=201)
async def add_git_credential(
    body: _GitCredentialCreate,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    if not _CRED_NAME_RE.fullmatch(body.name):
        raise HTTPException(status_code=422, detail=f"Invalid credential name: {body.name!r}")
    host = body.host.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
    if not host:
        raise HTTPException(status_code=422, detail="host is required")

    cfg = load_user(user.login)
    if any(c.name == body.name for c in cfg.git_credentials):
        raise HTTPException(status_code=409, detail=f"Credential {body.name!r} already exists")

    key_path = ""
    if body.kind == "ssh":
        if not body.private_key.strip():
            raise HTTPException(
                status_code=422, detail="private_key is required for SSH credentials"
            )
        key_dir = safe_user_path(user.login, "keys", "git", body.name)
        key_dir.mkdir(parents=True, exist_ok=True)
        key_file = key_dir / "id_ed25519"
        key_file.write_text(body.private_key.strip() + "\n", encoding="utf-8")
        key_file.chmod(0o600)
        key_path = str(key_file)
    elif body.kind == "token":
        if not body.token.strip():
            raise HTTPException(status_code=422, detail="token is required for PAT credentials")

    cfg.git_credentials.append(
        GitCredential(
            name=body.name,
            host=host,
            kind=body.kind,
            key_path=key_path,
            username=body.username.strip(),
            token=body.token.strip() if body.kind == "token" else "",
        )
    )
    save_user(user.login, cfg)
    _log.info("git_credential_added", login=user.login, name=body.name, kind=body.kind)
    return {"name": body.name, "host": host, "kind": body.kind}


class _GitCredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_name: str | None = None
    host: str | None = None
    kind: Literal["ssh", "token"] | None = None
    username: str | None = None
    token: str | None = None
    private_key: str | None = None


@router.patch("/git-credentials/{name}")
async def patch_git_credential(
    name: str,
    body: _GitCredentialUpdate,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    cfg = load_user(user.login)
    cred = next((c for c in cfg.git_credentials if c.name == name), None)
    if not cred:
        raise HTTPException(status_code=404, detail=f"Credential {name!r} not found")

    if body.new_name is not None:
        if not _CRED_NAME_RE.fullmatch(body.new_name):
            raise HTTPException(
                status_code=422, detail=f"Invalid credential name: {body.new_name!r}"
            )
        if body.new_name != name and any(c.name == body.new_name for c in cfg.git_credentials):
            raise HTTPException(
                status_code=409, detail=f"Credential {body.new_name!r} already exists"
            )

    effective_kind = body.kind if body.kind is not None else cred.kind
    effective_name = body.new_name if body.new_name is not None else name
    effective_host = (
        body.host.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        if body.host is not None
        else cred.host
    )
    effective_username = body.username.strip() if body.username is not None else cred.username

    if body.host is not None and not effective_host:
        raise HTTPException(status_code=422, detail="host is required")

    new_key_path = cred.key_path
    new_token = cred.token
    key_to_delete: Path | None = None

    if effective_kind == "ssh":
        new_token = ""
        if body.private_key is None or body.private_key == "__UNCHANGED__":
            if cred.kind != "ssh":
                raise HTTPException(
                    status_code=422, detail="private_key is required when changing kind to ssh"
                )
            if effective_name != name and cred.key_path:
                old_file = Path(cred.key_path)
                new_key_dir = safe_user_path(user.login, "keys", "git", effective_name)
                new_key_dir.mkdir(parents=True, exist_ok=True)
                new_key_file = new_key_dir / "id_ed25519"
                if old_file.exists():
                    shutil.copy2(str(old_file), str(new_key_file))
                    new_key_file.chmod(0o600)
                    key_to_delete = old_file
                new_key_path = str(new_key_file)
        else:
            old_key_path = cred.key_path
            key_dir = safe_user_path(user.login, "keys", "git", effective_name)
            key_dir.mkdir(parents=True, exist_ok=True)
            key_file = key_dir / "id_ed25519"
            key_file.write_text(body.private_key.strip() + "\n", encoding="utf-8")
            key_file.chmod(0o600)
            new_key_path = str(key_file)
            if old_key_path and old_key_path != new_key_path:
                key_to_delete = Path(old_key_path)
    else:
        new_key_path = ""
        if body.token is None or body.token == "__UNCHANGED__":
            if cred.kind != "token":
                raise HTTPException(
                    status_code=422, detail="token is required when changing kind to token"
                )
            new_token = cred.token
        else:
            if not body.token.strip():
                raise HTTPException(status_code=422, detail="token cannot be empty")
            new_token = body.token.strip()
        if cred.kind == "ssh" and cred.key_path:
            key_to_delete = Path(cred.key_path)

    updated = GitCredential(
        name=effective_name,
        host=effective_host,
        kind=effective_kind,
        key_path=new_key_path,
        username=effective_username,
        token=new_token,
    )
    cfg.git_credentials = [updated if c.name == name else c for c in cfg.git_credentials]

    if effective_name != name:
        for ws in cfg.workspaces:
            if ws.git_credential == name:
                ws.git_credential = effective_name
            for src in ws.extra_sources:
                if src.git_credential == name:
                    src.git_credential = effective_name

    save_user(user.login, cfg)

    if key_to_delete and key_to_delete.exists():
        key_to_delete.unlink()

    _log.info("git_credential_updated", login=user.login, name=name, new_name=effective_name)
    return {"name": effective_name, "host": effective_host, "kind": effective_kind}


@router.delete("/git-credentials/{name}")
async def delete_git_credential(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    cfg = load_user(user.login)
    cred = next((c for c in cfg.git_credentials if c.name == name), None)
    if not cred:
        raise HTTPException(status_code=404, detail=f"Credential {name!r} not found")
    cfg.git_credentials = [c for c in cfg.git_credentials if c.name != name]
    save_user(user.login, cfg)
    if cred.kind == "ssh" and cred.key_path:
        key_file = Path(cred.key_path)
        if key_file.exists():
            key_file.unlink()
    _log.info("git_credential_deleted", login=user.login, name=name)
    return {"deleted": name}


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
