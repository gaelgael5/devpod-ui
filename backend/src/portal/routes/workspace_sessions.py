from __future__ import annotations

import asyncio
import base64
import re
import shlex
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..config.store import _data_root, safe_user_path
from ..db.engine import get_conn
from ..db.recipes import load_recipes_as_dict
from ..devpod.exec import TMUX_SOCK_DETECT as _TMUX_SOCK_DETECT
from ..devpod.exec import tmux as _tmux
from ..devpod.exec import ws_exec
from ..recipes.models import _RECIPE_ID_RE

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["workspace-sessions"])


_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_SESSION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}$")


def _validate_ws_name(name: str) -> None:
    if not _WS_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail=f"Invalid workspace name {name!r}")


def _bundled_recipe_bases() -> list[Path]:
    repo = Path(__file__).resolve().parents[4] / "recipes"
    return [p for p in (repo, Path("/app/recipes")) if p.exists()]


def locate_start_sh(login: str, recipe_id: str) -> Path | None:
    """start.sh d'une recette start : perso → /data → recettes bundlées (image).

    Fallback bundlé : une recette livrée avec le produit reste utilisable même si son
    start.sh n'a pas été copié dans /data (lecture juste-à-temps, aucune synchro).
    """
    candidates = [
        safe_user_path(login, "recipes") / recipe_id / "start.sh",
        _data_root() / "recipes" / recipe_id / "start.sh",
        *[base / recipe_id / "start.sh" for base in _bundled_recipe_bases()],
    ]
    return next((c for c in candidates if c.exists()), None)


async def _ssh(ws_id: str, login: str, command: str, timeout: float = 30.0) -> tuple[int, str]:
    """Exécution non-interactive dans le devcontainer (façade `ws_exec`, ordre conservé)."""
    return await ws_exec(login, ws_id, command, timeout)


@router.get("/workspaces/{name}/sessions")
async def list_sessions(name: str, user: UserInfo = Depends(require_user)) -> list[str]:
    _validate_ws_name(name)
    ws_id = f"{user.login}-{name}"
    rc, output = await _ssh(
        ws_id,
        user.login,
        _tmux("list-sessions -F '#{session_name}' 2>/dev/null || true"),
    )
    if rc != 0:
        _log.warning("list_sessions_ssh_failed", ws_id=ws_id, output=output)
        return []
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
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    _validate_ws_name(name)
    if not _SESSION_NAME_RE.fullmatch(req.name):
        raise HTTPException(status_code=422, detail=f"Invalid session name {req.name!r}")
    ws_id = f"{user.login}-{name}"

    # Vérification de la disponibilité de tmux — auto-installation si absent (fallback B)
    rc_check, out_check = await _ssh(ws_id, user.login, "command -v tmux >/dev/null 2>&1")
    if rc_check != 0:
        if "timed out" in out_check:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Le workspace ne répond pas encore via SSH."
                    " Attendez quelques secondes et réessayez,"
                    " ou ajoutez la recipe 'tmux' lors de la création du workspace."
                ),
            )
        _log.info("tmux_absent_auto_installing", ws_id=ws_id)
        # Détection root vs non-root — sudo n'est pas toujours installé dans
        # les devcontainers qui tournent déjà en uid 0.
        _apt = (
            "if [ \"$(id -u)\" = '0' ]; then"
            " DEBIAN_FRONTEND=noninteractive apt-get update -qq"
            " && DEBIAN_FRONTEND=noninteractive apt-get install -y -q tmux;"
            " else"
            " DEBIAN_FRONTEND=noninteractive sudo -n apt-get update -qq"
            " && DEBIAN_FRONTEND=noninteractive sudo -n apt-get install -y -q tmux;"
            " fi"
        )
        rc_inst, out_inst = await _ssh(ws_id, user.login, _apt, timeout=120.0)
        if rc_inst != 0:
            raise HTTPException(
                status_code=422,
                detail=(
                    "tmux absent et installation automatique échouée."
                    " Ajoutez la recipe 'tmux' lors de la création du workspace."
                    f" Détail : {out_inst}"
                ),
            )
        _log.info("tmux_auto_installed", ws_id=ws_id)

    if req.start_recipe is not None:
        if not _RECIPE_ID_RE.fullmatch(req.start_recipe):
            raise HTTPException(status_code=422, detail=f"Invalid recipe id {req.start_recipe!r}")
        available = await load_recipes_as_dict(user.login, conn, type_filter="start")
        if req.start_recipe not in available:
            raise HTTPException(
                status_code=422, detail=f"Start recipe {req.start_recipe!r} not found"
            )
        start_sh = locate_start_sh(user.login, req.start_recipe)
        _log.info(
            "start_recipe_resolve",
            recipe=req.start_recipe,
            login=user.login,
            start_sh=str(start_sh) if start_sh else None,
            found=start_sh is not None,
        )
        if start_sh is None:
            raise HTTPException(
                status_code=422, detail=f"start.sh missing for {req.start_recipe!r}"
            )
        script = await asyncio.to_thread(start_sh.read_text, encoding="utf-8")
        b64 = base64.b64encode(script.encode()).decode()
        run_cmd = f'bash -lc "$(echo {b64} | base64 -d)"'
        # Les deux commandes tmux partagent le même socket détecté.
        command = (
            f"{_TMUX_SOCK_DETECT}; "
            f'TSOCK="${{TMUX_SOCK:+-S "$TMUX_SOCK"}}"; '
            f"tmux $TSOCK new-session -d -s {shlex.quote(req.name)}"
            f" && tmux $TSOCK send-keys -t {shlex.quote(req.name)} {shlex.quote(run_cmd)} Enter"
        )
    else:
        command = _tmux(f"new-session -d -s {shlex.quote(req.name)}")

    rc, output = await _ssh(ws_id, user.login, command)
    if rc != 0:
        raise HTTPException(status_code=502, detail=f"Failed to create tmux session: {output}")

    _log.info("session_created", ws_id=ws_id, session=req.name, start_recipe=req.start_recipe)
    return {"name": req.name}


@router.delete("/workspaces/{name}/sessions/{session_name}", status_code=204)
async def delete_session(
    name: str,
    session_name: str,
    user: UserInfo = Depends(require_user),
) -> None:
    _validate_ws_name(name)
    if not _SESSION_NAME_RE.fullmatch(session_name):
        raise HTTPException(status_code=422, detail=f"Invalid session name {session_name!r}")
    ws_id = f"{user.login}-{name}"
    rc, output = await _ssh(
        ws_id,
        user.login,
        _tmux(f"kill-session -t {shlex.quote(session_name)}"),
    )
    if rc != 0:
        raise HTTPException(status_code=502, detail=f"Failed to kill tmux session: {output}")
    _log.info("session_deleted", ws_id=ws_id, session=session_name)
