"""Primitives MCP « skills » — surface agent du registre skills.sh.

Invariant de sécurité (epic skills) : la surface MCP **pétitionne et
restreint**, elle n'**accorde jamais**. Donc :
  - search   (read)  : proxy skills.sh, lecture seule ;
  - request_approval (write) : crée un grant `pending` — AUCUN approve ici ;
  - place / remove (exec) : self-provisioning d'une skill DÉJÀ validée
    (grant `granted`) dans le workspace de l'agent — il ne peut placer que ce
    que l'humain a béni ;
  - pause (write) : restreindre est sain ; il n'existe PAS de resume MCP
    (remise en service = action humaine, asymétrie voulue).

L'agent opère on-behalf-of le propriétaire du workspace (owner_login) ; son
sujet OIDC (users.sub) porte les grants — cohérent avec l'UI. Un compte non
encore ancré OIDC (sub NULL) ne peut pas manipuler de skills (fail closed).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from ...db.skills import (
    create_or_get_grant,
    get_grant,
    list_workspace_skills,
    pause_grant,
)
from ...db.tables import users
from ...skills.adapter import SkillsShError, get_skills_adapter
from ...skills.placement import PlacementError, place_skill, remove_skill
from .errors import DevpodToolError

_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+){1,5}$")


def _require_str(args: dict[str, Any], key: str) -> str:
    val = args.get(key)
    if not isinstance(val, str) or not val.strip():
        raise DevpodToolError(f"paramètre requis manquant ou vide: {key!r}")
    return val.strip()


def _skill_id(args: dict[str, Any]) -> str:
    v = _require_str(args, "skill_id")
    if (
        len(v) > 300
        or not _SKILL_ID_RE.fullmatch(v)
        or any(set(seg) == {"."} for seg in v.split("/"))
    ):
        raise DevpodToolError("skill_id invalide (attendu : source/skillId)")
    return v


def _ws_id(args: dict[str, Any], owner_login: str) -> str:
    name = _require_str(args, "workspace")
    if not _WS_NAME_RE.fullmatch(name):
        raise DevpodToolError("nom de workspace invalide")
    return f"{owner_login}-{name}"


async def _subject(conn: AsyncConnection, owner_login: str) -> str:
    sub = (
        await conn.execute(select(users.c.sub).where(users.c.login == owner_login))
    ).scalar_one_or_none()
    if not sub:
        raise DevpodToolError("compte non ancré OIDC (aucun sub) — connectez-vous via OIDC d'abord")
    return str(sub)


async def _skills_search(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    query = _require_str(args, "query")
    search_type = str(args.get("search_type", "fuzzy"))
    if search_type not in ("fuzzy", "semantic"):
        raise DevpodToolError("search_type doit être 'fuzzy' ou 'semantic'")
    try:
        # Toujours sans clé côté agent (l'installation l'est aussi).
        return await get_skills_adapter().search(query, search_type)
    except SkillsShError as exc:
        raise DevpodToolError(str(exc)) from exc


async def _skills_request_approval(
    conn: AsyncConnection, args: dict[str, Any], owner_login: str
) -> Any:
    """Pétition : crée un grant `pending` (write-only). L'agent NE valide jamais
    — la demande atterrit dans l'onglet Validations pour décision humaine."""
    skill_id = _skill_id(args)
    reason = str(args.get("reason", ""))[:500]
    subject = await _subject(conn, owner_login)
    grant, created = await create_or_get_grant(subject, skill_id, conn)
    return {
        "skill_id": skill_id,
        "grant_statut": grant["statut"],
        "created": created,
        "reason": reason,
        "note": "Validation requise par un humain (onglet Validations).",
    }


async def _skills_place(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    """Self-provisioning : place une skill DÉJÀ validée (grant granted) dans le
    workspace de l'agent. 409-like si non validée (il ne peut placer que le béni)."""
    ws_id = _ws_id(args, owner_login)
    skill_id = _skill_id(args)
    subject = await _subject(conn, owner_login)
    grant = await get_grant(subject, skill_id, conn)
    if grant is None:
        raise DevpodToolError("aucun grant pour cette skill — demandez d'abord l'approbation")
    if grant["statut"] != "granted":
        raise DevpodToolError(
            f"grant {grant['statut']} — validation humaine requise avant placement"
        )
    try:
        return await place_skill(owner_login, ws_id, grant, conn)
    except PlacementError as exc:
        raise DevpodToolError(str(exc)) from exc


async def _skills_remove(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    ws_id = _ws_id(args, owner_login)
    skill_id = _skill_id(args)
    subject = await _subject(conn, owner_login)
    rows = await list_workspace_skills(ws_id, subject, conn)
    target = next((r for r in rows if r["skill_id"] == skill_id), None)
    if target is None:
        raise DevpodToolError("skill non placée dans ce workspace")
    await remove_skill(owner_login, ws_id, skill_id, target["placement_id"], conn)
    return {"skill_id": skill_id, "workspace": args.get("workspace"), "removed": True}


async def _skills_pause(conn: AsyncConnection, args: dict[str, Any], owner_login: str) -> Any:
    """Restreindre est sain → autorisé côté MCP. Pas de resume (humain seul)."""
    skill_id = _skill_id(args)
    subject = await _subject(conn, owner_login)
    grant = await get_grant(subject, skill_id, conn)
    if grant is None or grant["statut"] != "granted":
        raise DevpodToolError("skill non validée (rien à mettre en pause)")
    await pause_grant(grant["id"], conn)
    return {
        "skill_id": skill_id,
        "grant_statut": "paused",
        "note": "Remise en service = action humaine (pas de resume MCP).",
    }


SKILLS_IMPLS = {
    "skills_search": _skills_search,
    "skills_request_approval": _skills_request_approval,
    "skills_place": _skills_place,
    "skills_remove": _skills_remove,
    "skills_pause": _skills_pause,
}
