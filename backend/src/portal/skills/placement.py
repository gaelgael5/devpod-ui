"""Placement des skills validées dans les workspaces (installation + vérif hash).

Flux (story Placement) :
1. seul un grant `granted` du sujet peut être placé ;
2. installation DANS le workspace : `npx skills add <source> --skill <id>
   --agent claude-code -y --copy` (TOUJOURS sans clé API) — vérifié contre la
   CLI réelle : installe `.claude/skills/<id>/SKILL.md` à la racine ;
3. vérification post-install : hash de ce qui a ATTERRI (installed_hash) vs
   approved_hash du grant. Match → `verified` (la gateway route). Divergence
   (npx tire le HEAD non épinglé) → `unverified`, PAS de routage, et le grant
   retombe `pending` (re-validation demandée). Vérification à l'installation
   uniquement — pas de check continu.

Le disque n'est qu'un cache : le retrait supprime placement + fichiers, le
grant survit (re-plaçable ailleurs sans re-validation).
"""
from __future__ import annotations

import shlex
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.skills import (
    create_or_get_placement,
    delete_placement,
    mark_grant_pending,
    set_placement_placed,
    set_placement_verified,
)
from ..devpod.exec import ws_exec

_log = structlog.get_logger(__name__)

_INSTALL_TIMEOUT_S = 300.0
_EXEC_TIMEOUT_S = 30.0


class PlacementError(Exception):
    """Échec d'installation/retrait dans le workspace (sortie CLI incluse)."""


def split_skill_id(skill_id: str) -> tuple[str, str]:
    """`source/skillId` → (source, skillId) — le skillId est le dernier segment."""
    source, _, sid = skill_id.rpartition("/")
    return source, sid


async def place_skill(
    login: str, ws_id: str, grant: dict[str, Any], conn: AsyncConnection
) -> dict[str, Any]:
    """Installe la skill du grant dans le workspace et vérifie le hash.

    Retourne le placement final (statut verified/unverified). Le skill_id a été
    validé par la route (segments sûrs) — il est de plus shell-quoté.
    """
    source, sid = split_skill_id(grant["skill_id"])
    placement, _ = await create_or_get_placement(grant["id"], ws_id, conn)

    install_cmd = (
        f"cd /workspaces/{shlex.quote(ws_id)} && "
        f"npx --yes skills add {shlex.quote(source)} --skill {shlex.quote(sid)} "
        f"--agent claude-code -y --copy"
    )
    rc, out = await ws_exec(login, ws_id, install_cmd, timeout=_INSTALL_TIMEOUT_S)
    if rc != 0:
        raise PlacementError(f"npx skills add a échoué (code {rc}) : {out[-500:]}")

    # Hash de ce qui a RÉELLEMENT atterri sur le disque du workspace.
    hash_cmd = (
        f"sha256sum /workspaces/{shlex.quote(ws_id)}/.claude/skills/"
        f"{shlex.quote(sid)}/SKILL.md"
    )
    rc, out = await ws_exec(login, ws_id, hash_cmd, timeout=_EXEC_TIMEOUT_S)
    if rc != 0:
        raise PlacementError(f"SKILL.md introuvable après install : {out[-300:]}")
    installed_hash = "sha256:" + out.split()[0]

    await set_placement_placed(placement["id"], installed_hash, conn)
    ok = installed_hash == grant["approved_hash"]
    await set_placement_verified(placement["id"], ok, conn)
    if not ok:
        # HEAD non épinglé : le contenu a dérivé depuis la validation → le
        # grant retombe pending (re-validation), approved_hash conservé pour
        # comparaison. Le placement unverified n'est JAMAIS routé.
        await mark_grant_pending(grant["id"], conn)
    _log.info(
        "skill_placed",
        login=login,
        ws_id=ws_id,
        skill_id=grant["skill_id"],
        verified=ok,
        installed_hash=installed_hash,
    )
    return {
        **placement,
        "statut": "verified" if ok else "unverified",
        "installed_hash": installed_hash,
    }


async def remove_skill(
    login: str, ws_id: str, skill_id: str, placement_id: int, conn: AsyncConnection
) -> None:
    """Retire la skill du workspace : fichiers (cache) + ligne placement.
    Le grant per-user reste intact."""
    _, sid = split_skill_id(skill_id)
    rm_cmd = f"rm -rf /workspaces/{shlex.quote(ws_id)}/.claude/skills/{shlex.quote(sid)}"
    rc, out = await ws_exec(login, ws_id, rm_cmd, timeout=_EXEC_TIMEOUT_S)
    if rc != 0:
        # Best-effort sur le disque (simple cache) — mais on le journalise.
        _log.warning("skill_files_removal_failed", ws_id=ws_id, skill_id=skill_id, out=out[-200:])
    await delete_placement(placement_id, conn)
    _log.info("skill_removed", login=login, ws_id=ws_id, skill_id=skill_id)
