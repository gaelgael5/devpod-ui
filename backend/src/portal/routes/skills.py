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
from ..db.skills import (
    approve_grant,
    create_or_get_grant,
    get_grant_by_id,
    list_grants,
    pause_grant,
    resume_grant,
    revoke_grant,
)
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


# ── Cycle de vie des grants (onglet Validations) ─────────────────────────────
# Toutes ces routes sont des actions HUMAINES authentifiées (session Keycloak).
# La surface MCP n'exposera que pause (restreindre) — jamais approve/resume.


async def _own_grant(
    grant_id: int, user: UserInfo, conn: AsyncConnection
) -> dict[str, Any]:
    """Le grant s'il appartient au sujet de la session — 404 sinon (pas de
    fuite d'existence des grants d'autrui)."""
    grant = await get_grant_by_id(grant_id, conn)
    if grant is None or grant["user_subject"] != _subject(user):
        raise HTTPException(status_code=404, detail="grant introuvable")
    return grant


def _split_skill_id(skill_id: str) -> tuple[str, str]:
    """`source/skillId` → (source, skillId) — le skillId est le dernier segment."""
    source, _, sid = skill_id.rpartition("/")
    return source, sid


@router.get("/skills/grants/{grant_id}/skillmd")
async def get_grant_skill_md(
    grant_id: int,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Contenu canonique du SKILL.md + hash courant, avec l'approved_hash du
    grant : l'écran de validation compare les deux (décision informée, y
    compris re-validation après dérive)."""
    grant = await _own_grant(grant_id, user, conn)
    source, sid = _split_skill_id(grant["skill_id"])
    try:
        doc = await get_skills_adapter().skill_md(source, sid)
    except SkillsShError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {**doc, "approved_hash": grant["approved_hash"]}


@router.post("/skills/grants/{grant_id}/approve")
async def approve(
    grant_id: int,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Validation humaine : granted + approved_hash figé au hash COURANT du
    SKILL.md canonique (récupéré côté serveur — le client ne fournit jamais le
    hash, sinon un client malveillant validerait un contenu différent)."""
    grant = await _own_grant(grant_id, user, conn)
    if grant["statut"] != "pending":
        raise HTTPException(status_code=409, detail=f"grant {grant['statut']}, pas pending")
    source, sid = _split_skill_id(grant["skill_id"])
    try:
        doc = await get_skills_adapter().skill_md(source, sid)
    except SkillsShError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await approve_grant(grant_id, doc["hash"], conn)
    _log.info(
        "skill_grant_approved",
        login=user.login,
        subject=user.sub,
        skill_id=grant["skill_id"],
        approved_hash=doc["hash"],
    )
    updated = await get_grant_by_id(grant_id, conn)
    assert updated is not None
    return updated


@router.post("/skills/grants/{grant_id}/revoke")
async def revoke(
    grant_id: int,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Révocation humaine — cascade sur tous les placements via la requête
    d'ensemble effectif (le routage s'arrête immédiatement, le scrub disque
    est optionnel)."""
    grant = await _own_grant(grant_id, user, conn)
    if grant["statut"] == "revoked":
        raise HTTPException(status_code=409, detail="grant déjà révoqué")
    await revoke_grant(grant_id, conn)
    _log.info(
        "skill_grant_revoked",
        login=user.login,
        subject=user.sub,
        skill_id=grant["skill_id"],
    )
    updated = await get_grant_by_id(grant_id, conn)
    assert updated is not None
    return updated


@router.post("/skills/grants/{grant_id}/pause")
async def pause(
    grant_id: int,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Pause : suspend le routage sans révoquer. (Également exposable côté MCP :
    restreindre est sain.)"""
    grant = await _own_grant(grant_id, user, conn)
    if grant["statut"] != "granted":
        raise HTTPException(status_code=409, detail=f"grant {grant['statut']}, pas granted")
    await pause_grant(grant_id, conn)
    _log.info(
        "skill_grant_paused", login=user.login, subject=user.sub, skill_id=grant["skill_id"]
    )
    updated = await get_grant_by_id(grant_id, conn)
    assert updated is not None
    return updated


@router.post("/skills/grants/{grant_id}/resume")
async def resume(
    grant_id: int,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Remise en service : ré-accorder un accès → action humaine UNIQUEMENT
    (asymétrie pause/resume — jamais de primitive MCP)."""
    grant = await _own_grant(grant_id, user, conn)
    if grant["statut"] != "paused":
        raise HTTPException(status_code=409, detail=f"grant {grant['statut']}, pas paused")
    await resume_grant(grant_id, conn)
    _log.info(
        "skill_grant_resumed", login=user.login, subject=user.sub, skill_id=grant["skill_id"]
    )
    updated = await get_grant_by_id(grant_id, conn)
    assert updated is not None
    return updated
