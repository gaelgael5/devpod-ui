"""Vue centralisée des sessions actives — `GET /sessions` et `POST /sessions/close`.

L'agrégation (`GET`) énumère les terminaux (conteneurs tmux, hosts admin, VM de
test) accessibles à l'appelant. La création reste portée par les endpoints
existants `POST /me/workspaces/{name}/sessions`.

`POST /sessions/close` centralise la fermeture, seule primitive absente jusque-là
pour les familles host/test (qui n'ont pas de session tmux à supprimer) : elle
détache le pont vivant, et — pour un workspace — tue en plus la session tmux.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, UsernameError, require_user, validate_username
from ..sessions import registry
from ..sessions.aggregate import list_sessions
from ..sessions.close_ops import kill_tmux_session
from ..settings import get_settings

router = APIRouter(tags=["sessions"])

_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_SESSION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}$")


def _is_admin(user: UserInfo) -> bool:
    """Admin = rôle admin OIDC présent dans les rôles de session (comme ssh_proxy)."""
    return get_settings().oidc_admin_role in user.roles


@router.get("/sessions")
async def get_sessions(user: UserInfo = Depends(require_user)) -> list[dict[str, Any]]:
    return await list_sessions(login=user.login, is_admin=_is_admin(user))


class CloseSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: registry.Family
    target: str
    owner: str
    session: str | None = None


def _workspace_name(target: str, owner: str) -> str:
    """Nom de workspace extrait du `ws_id` (`<owner>-<name>`), validé (anti-injection)."""
    prefix = f"{owner}-"
    if not target.startswith(prefix):
        raise HTTPException(status_code=422, detail="target/owner mismatch")
    name = target[len(prefix) :]
    if not _WS_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail=f"Invalid workspace name {name!r}")
    return name


@router.post("/sessions/close", status_code=204)
async def close_session(req: CloseSessionRequest, user: UserInfo = Depends(require_user)) -> None:
    admin = _is_admin(user)
    try:
        validate_username(req.owner)
    except UsernameError as exc:
        raise HTTPException(status_code=422, detail="Invalid owner") from exc
    if req.owner != user.login and not admin:
        raise HTTPException(status_code=403, detail="Not allowed to close another user's session")
    if req.session is not None and not _SESSION_NAME_RE.fullmatch(req.session):
        raise HTTPException(status_code=422, detail=f"Invalid session name {req.session!r}")

    # Détache le pont vivant (toutes familles). owner=None en vue admin → ferme
    # l'instance quel que soit son propriétaire ; sinon restreint au login.
    registry.close_matching(
        family=req.family,
        target=req.target,
        session=req.session,
        owner=None if admin else user.login,
    )

    # Workspace : tue aussi la session tmux sous-jacente (décision produit).
    if req.family == "workspace" and req.session:
        name = _workspace_name(req.target, req.owner)
        await kill_tmux_session(
            owner=req.owner, name=name, session_name=req.session, actor=user.login
        )
