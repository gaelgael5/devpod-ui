"""Skills (skills.sh) — recherche, audit et demandes de validation.

`GET /me/skills/search`, `GET /me/skills/audit` : lectures proxifiées par
l'adaptateur (cache TTL). La clé API optionnelle est référencée par slug de
secret (type SKILLS_SH) et révélée côté serveur — jamais transmise au client.

`POST /me/skills/grants` : demande de validation → grant `pending` per-user
(keyé sub OIDC). Ce n'est PAS une installation : aucune skill n'est utilisable
sans validation humaine explicite (onglet Validations). La route ne peut pas
accorder — elle pétitionne.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..db.engine import get_conn
from ..db.skills import create_or_get_grant, list_grants
from ..secrets.service import SecretNotFound, VaultLocked, reveal_secret
from ..skills.adapter import SkillsShError, get_skills_adapter

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["skills"])

_SECRET_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
# id skills.sh = "source/skillId" (ex. github/awesome-copilot/git-commit) :
# segments alphanumériques + . _ - séparés par des /.
_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+){1,5}$")


def _sid(request: Request) -> str:
    return str(request.session.get("session_id", ""))


def _subject(user: UserInfo) -> str:
    """Sujet OIDC porteur des grants. Fail closed si la session n'en a pas."""
    if not user.sub:
        raise HTTPException(
            status_code=403, detail="session sans sujet OIDC — reconnectez-vous"
        )
    return user.sub


async def _resolve_key(
    login: str, session_id: str, secret_slug: str, conn: AsyncConnection
) -> str:
    """Valeur claire du secret SKILLS_SH, ou chaîne vide si aucun secret."""
    if not secret_slug:
        return ""
    if not _SECRET_SLUG_RE.fullmatch(secret_slug):
        raise HTTPException(status_code=422, detail="secret_slug invalide")
    try:
        return await reveal_secret(login, session_id, secret_slug, conn)
    except VaultLocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SecretNotFound as exc:
        raise HTTPException(status_code=404, detail="secret introuvable") from exc


@router.get("/skills/search")
async def search_skills(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    search_type: str = Query(default="fuzzy", pattern=r"^(fuzzy|semantic)$"),
    secret_slug: str = Query(default=""),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    key = await _resolve_key(user.login, _sid(request), secret_slug, conn)
    try:
        return await get_skills_adapter().search(q, search_type, api_key=key or None)
    except SkillsShError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/skills/audit")
async def audit_skills(
    request: Request,
    source: str = Query(min_length=1, max_length=200),
    skills: str = Query(min_length=1, max_length=1000),
    secret_slug: str = Query(default=""),
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Audit sécurité (ath/socket/snyk/zeroleaks) d'une ou plusieurs skills
    d'une même source — `skills` = ids séparés par des virgules."""
    key = await _resolve_key(user.login, _sid(request), secret_slug, conn)
    skill_ids = [s.strip() for s in skills.split(",") if s.strip()]
    if not skill_ids:
        raise HTTPException(status_code=422, detail="skills vide")
    try:
        return await get_skills_adapter().audit(source, skill_ids, api_key=key or None)
    except SkillsShError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class GrantRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str

    @field_validator("skill_id")
    @classmethod
    def _skill_id(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 300 or not _SKILL_ID_RE.fullmatch(v):
            raise ValueError("skill_id invalide (attendu : source/skillId)")
        # Un segment composé uniquement de points (., ..) est un chemin relatif
        # déguisé — le skill_id alimentera des chemins d'installation.
        if any(set(seg) == {"."} for seg in v.split("/")):
            raise ValueError("skill_id invalide (segment '.' ou '..')")
        return v


@router.get("/skills/grants")
async def get_grants(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return await list_grants(_subject(user), conn)


@router.post("/skills/grants", status_code=201)
async def request_grant(
    body: GrantRequestBody,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Demande de validation (grant pending). Idempotent : si un grant existe
    déjà pour (user, skill) il est retourné tel quel — une skill révoquée ne
    repasse jamais en pending par ce chemin."""
    grant, created = await create_or_get_grant(_subject(user), body.skill_id, conn)
    if created:
        _log.info(
            "skill_grant_requested",
            login=user.login,
            subject=user.sub,
            skill_id=body.skill_id,
        )
    return {**grant, "created": created}
