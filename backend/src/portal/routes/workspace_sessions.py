from __future__ import annotations

import asyncio
import base64
import os
import re
import shlex

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_user
from ..config.store import _data_root, safe_user_path
from ..recipes.models import _RECIPE_ID_RE
from ..recipes.registry import RecipeRegistry

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["workspace-sessions"])

_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_SESSION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}$")


def _validate_ws_name(name: str) -> None:
    if not _WS_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail=f"Invalid workspace name {name!r}")


async def _ssh(ws_id: str, login: str, command: str, timeout: float = 10.0) -> tuple[int, str]:
    """Exécute une commande non-interactive dans le devcontainer via SSH."""
    ssh_host = f"{ws_id}.devpod"
    if ssh_host.startswith("-"):
        raise ValueError(f"Insecure ws_id: {ws_id!r}")
    env = {
        **dict(os.environ),
        "DEVPOD_HOME": str(safe_user_path(login, "devpod")),
        "HOME": os.environ.get("HOME", "/root"),
    }
    proc = await asyncio.create_subprocess_exec(
        "ssh", "-o", "LogLevel=QUIET", "--", ssh_host, command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 1, "timeout"
    return proc.returncode or 0, stdout.decode(errors="replace")


@router.get("/workspaces/{name}/sessions")
async def list_sessions(name: str, user: UserInfo = Depends(require_user)) -> list[str]:
    _validate_ws_name(name)
    ws_id = f"{user.login}-{name}"
    _, output = await _ssh(
        ws_id, user.login,
        "tmux list-sessions -F '#{session_name}' 2>/dev/null || true",
    )
    return [s for s in output.strip().splitlines() if s]


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    start_recipe: str | None = None


@router.post("/workspaces/{name}/sessions", status_code=201)
async def create_session(
    name: str,
    req: CreateSessionRequest,
    user: UserInfo = Depends(require_user),
) -> dict[str, str]:
    _validate_ws_name(name)
    if not _SESSION_NAME_RE.fullmatch(req.name):
        raise HTTPException(status_code=422, detail=f"Invalid session name {req.name!r}")
    ws_id = f"{user.login}-{name}"

    if req.start_recipe is not None:
        if not _RECIPE_ID_RE.fullmatch(req.start_recipe):
            raise HTTPException(status_code=422, detail=f"Invalid recipe id {req.start_recipe!r}")
        data_root = _data_root()
        shared_dir = data_root / "recipes"
        personal_dir = safe_user_path(user.login, "recipes")
        registry = RecipeRegistry(builtin_dir=None, shared_dir=shared_dir)
        shared = await asyncio.to_thread(registry.load_shared)
        personal = await asyncio.to_thread(registry.load_dir, personal_dir)
        available = {**shared, **personal}
        recipe = available.get(req.start_recipe)
        if recipe is None or recipe.type != "start":
            raise HTTPException(status_code=422, detail=f"Start recipe {req.start_recipe!r} not found")
        recipe_dir = (
            personal_dir / req.start_recipe
            if (personal_dir / req.start_recipe).exists()
            else shared_dir / req.start_recipe
        )
        start_sh = recipe_dir / "start.sh"
        if not start_sh.exists():
            raise HTTPException(status_code=422, detail=f"start.sh missing for {req.start_recipe!r}")
        script = await asyncio.to_thread(start_sh.read_text, encoding="utf-8")
        b64 = base64.b64encode(script.encode()).decode()
        run_cmd = f'bash -lc "$(echo {b64} | base64 -d)"'
        command = (
            f"tmux new-session -d -s {shlex.quote(req.name)}"
            f" && tmux send-keys -t {shlex.quote(req.name)} {shlex.quote(run_cmd)} Enter"
        )
    else:
        command = f"tmux new-session -d -s {shlex.quote(req.name)}"

    rc, output = await _ssh(ws_id, user.login, command)
    if rc != 0:
        raise HTTPException(status_code=502, detail=f"Failed to create tmux session: {output.strip()}")

    _log.info("session_created", ws_id=ws_id, session=req.name, start_recipe=req.start_recipe)
    return {"name": req.name}
