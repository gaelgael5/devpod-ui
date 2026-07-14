"""Placement des skills validées dans les workspaces — `/me/workspaces/{name}/skills`.

Décision OPÉRATIONNELLE (par opposition au grant, décision de confiance) :
seule une skill au grant `granted` du sujet peut être placée. L'installation
tourne dans le workspace (npx skills add, sans clé) puis le hash installé est
vérifié contre l'approved_hash — voir portal.skills.placement.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db.engine import get_conn
from ..db.skills import get_grant, list_workspace_skills
from ..skills.placement import PlacementError, place_skill, remove_skill

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["skills"])

_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+){1,5}$")


def _ws_id(login: str, name: str) -> str:
    if not _WS_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="nom de workspace invalide")
    return f"{login}-{name}"


def _subject(user: UserInfo) -> str:
    if not user.sub:
        raise HTTPException(
            status_code=403, detail="session sans sujet OIDC — reconnectez-vous"
        )
    return user.sub


class PlaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str

    @field_validator("skill_id")
    @classmethod
    def _skill_id(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 300 or not _SKILL_ID_RE.fullmatch(v):
            raise ValueError("skill_id invalide (attendu : source/skillId)")
        if any(set(seg) == {"."} for seg in v.split("/")):
            raise ValueError("skill_id invalide (segment '.' ou '..')")
        return v


@router.get("/workspaces/{name}/skills")
async def get_workspace_skills(
    name: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await list_workspace_skills(_ws_id(user.login, name), _subject(user), conn)


@router.post("/workspaces/{name}/skills", status_code=201)
async def place(
    name: str,
    body: PlaceBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Installe une skill VALIDÉE dans le workspace. 409 si le grant n'est pas
    `granted` (pending/paused/revoked : rien n'est jamais installé sans
    validation humaine préalable)."""
    ws_id = _ws_id(user.login, name)
    grant = await get_grant(_subject(user), body.skill_id, conn)
    if grant is None:
        raise HTTPException(status_code=404, detail="aucun grant pour cette skill")
    if grant["statut"] != "granted":
        raise HTTPException(
            status_code=409, detail=f"grant {grant['statut']} — validation requise"
        )
    try:
        return await place_skill(user.login, ws_id, grant, conn)
    except PlacementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/workspaces/{name}/skills/{placement_id}", status_code=204)
async def unplace(
    name: str,
    placement_id: int,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    """Retire la skill du workspace (fichiers = cache + ligne placement).
    Le grant reste intact — re-plaçable ailleurs sans re-validation."""
    ws_id = _ws_id(user.login, name)
    rows = await list_workspace_skills(ws_id, _subject(user), conn)
    target = next((r for r in rows if r["placement_id"] == placement_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="placement introuvable")
    await remove_skill(user.login, ws_id, target["skill_id"], placement_id, conn)
