"""Persistance du registre skills.sh : grants (autorisation) + placements (installation).

Deux machines à états distinctes liées par FK — voir le commentaire des tables
dans tables.py. Ce module n'expose que des primitives : les règles métier
(qui a le droit de valider, MCP write-only, etc.) vivent dans les routes/le
service, JAMAIS ici.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import skill_grants, skill_placements

GRANT_STATUTS = ("requested", "pending", "granted", "paused", "revoked")
PLACEMENT_STATUTS = ("requested", "placed", "verified", "unverified")


# ── Grants (autorisation per-user, human-gated) ───────────────────────────────


async def create_or_get_grant(
    user_subject: str, skill_id: str, conn: AsyncConnection
) -> tuple[dict[str, Any], bool]:
    """Demande de validation : crée le grant en `pending` s'il n'existe pas.

    Idempotent : si un grant (user, skill) existe déjà — quel que soit son
    statut — il est retourné tel quel (created=False). Re-demander une skill
    révoquée ne la repasse PAS en pending : la révocation est une décision
    humaine que seule une action humaine peut lever.
    """
    existing = await get_grant(user_subject, skill_id, conn)
    if existing is not None:
        return existing, False
    row = (
        await conn.execute(
            skill_grants.insert()
            .values(user_subject=user_subject, skill_id=skill_id, statut="pending")
            .returning(skill_grants)
        )
    ).mappings().one()
    return dict(row), True


async def get_grant(
    user_subject: str, skill_id: str, conn: AsyncConnection
) -> dict[str, Any] | None:
    row = (
        await conn.execute(
            select(skill_grants)
            .where(skill_grants.c.user_subject == user_subject)
            .where(skill_grants.c.skill_id == skill_id)
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def get_grant_by_id(grant_id: int, conn: AsyncConnection) -> dict[str, Any] | None:
    row = (
        await conn.execute(select(skill_grants).where(skill_grants.c.id == grant_id))
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def list_grants(user_subject: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            select(skill_grants)
            .where(skill_grants.c.user_subject == user_subject)
            .order_by(skill_grants.c.id)
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def list_pending_grants(
    user_subject: str, conn: AsyncConnection
) -> list[dict[str, Any]]:
    """Demandes en attente de validation humaine — inclut les re-validations
    après dérive de hash (approved_hash non NULL + statut pending)."""
    rows = (
        await conn.execute(
            select(skill_grants)
            .where(skill_grants.c.user_subject == user_subject)
            .where(skill_grants.c.statut == "pending")
            .order_by(skill_grants.c.id)
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def approve_grant(grant_id: int, approved_hash: str, conn: AsyncConnection) -> bool:
    """Validation HUMAINE : granted + approved_hash figé. Jamais appelée par MCP."""
    result = await conn.execute(
        update(skill_grants)
        .where(skill_grants.c.id == grant_id)
        .values(
            statut="granted",
            approved_hash=approved_hash,
            granted_at=func.now(),
            updated_at=func.now(),
        )
    )
    return (result.rowcount or 0) > 0


async def mark_grant_pending(grant_id: int, conn: AsyncConnection) -> bool:
    """Dérive de hash : retombe en pending. approved_hash CONSERVÉ (l'écran de
    re-validation compare l'ancien hash approuvé au nouveau contenu)."""
    result = await conn.execute(
        update(skill_grants)
        .where(skill_grants.c.id == grant_id)
        .values(statut="pending", updated_at=func.now())
    )
    return (result.rowcount or 0) > 0


async def pause_grant(grant_id: int, conn: AsyncConnection) -> bool:
    """Pause (IHM ou MCP). La remise en service est humaine uniquement."""
    result = await conn.execute(
        update(skill_grants)
        .where(skill_grants.c.id == grant_id)
        .values(statut="paused", updated_at=func.now())
    )
    return (result.rowcount or 0) > 0


async def resume_grant(grant_id: int, conn: AsyncConnection) -> bool:
    """Remise en service (action HUMAINE uniquement — jamais exposée en MCP)."""
    result = await conn.execute(
        update(skill_grants)
        .where(skill_grants.c.id == grant_id)
        .where(skill_grants.c.statut == "paused")
        .values(statut="granted", updated_at=func.now())
    )
    return (result.rowcount or 0) > 0


async def revoke_grant(grant_id: int, conn: AsyncConnection) -> bool:
    """Révocation HUMAINE. Coupe le routage de tous les placements (invariant :
    l'ensemble effectif joint le statut du grant — aucune ligne placement n'est
    touchée, elles restent en base pour l'audit)."""
    result = await conn.execute(
        update(skill_grants)
        .where(skill_grants.c.id == grant_id)
        .values(statut="revoked", revoked_at=func.now(), updated_at=func.now())
    )
    return (result.rowcount or 0) > 0


# ── Placements (installation per-workspace) ───────────────────────────────────


async def create_or_get_placement(
    grant_id: int, workspace_id: str, conn: AsyncConnection
) -> tuple[dict[str, Any], bool]:
    """Placement demandé pour un workspace. Idempotent sur (grant, workspace)."""
    existing = (
        await conn.execute(
            select(skill_placements)
            .where(skill_placements.c.grant_id == grant_id)
            .where(skill_placements.c.workspace_id == workspace_id)
        )
    ).mappings().one_or_none()
    if existing is not None:
        return dict(existing), False
    row = (
        await conn.execute(
            skill_placements.insert()
            .values(grant_id=grant_id, workspace_id=workspace_id, statut="requested")
            .returning(skill_placements)
        )
    ).mappings().one()
    return dict(row), True


async def set_placement_placed(
    placement_id: int, installed_hash: str, conn: AsyncConnection
) -> bool:
    """Installation faite : fige installed_hash (la copie disque ne bouge plus,
    pas de check continu — vérification à l'installation uniquement)."""
    result = await conn.execute(
        update(skill_placements)
        .where(skill_placements.c.id == placement_id)
        .values(statut="placed", installed_hash=installed_hash, updated_at=func.now())
    )
    return (result.rowcount or 0) > 0


async def set_placement_verified(
    placement_id: int, ok: bool, conn: AsyncConnection
) -> bool:
    """Résultat de la vérification post-install : verified ou unverified."""
    result = await conn.execute(
        update(skill_placements)
        .where(skill_placements.c.id == placement_id)
        .values(statut="verified" if ok else "unverified", updated_at=func.now())
    )
    return (result.rowcount or 0) > 0


async def delete_placement(placement_id: int, conn: AsyncConnection) -> bool:
    """Retrait d'une skill d'un workspace. Le grant (autorisation) survit."""
    result = await conn.execute(
        delete(skill_placements).where(skill_placements.c.id == placement_id)
    )
    return (result.rowcount or 0) > 0


async def list_placements(workspace_id: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            select(skill_placements)
            .where(skill_placements.c.workspace_id == workspace_id)
            .order_by(skill_placements.c.id)
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def list_placements_for_grant(
    grant_id: int, conn: AsyncConnection
) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            select(skill_placements)
            .where(skill_placements.c.grant_id == grant_id)
            .order_by(skill_placements.c.id)
        )
    ).mappings().all()
    return [dict(r) for r in rows]


# ── Ensemble effectif (requête de routage de la gateway) ─────────────────────


async def list_effective_skills(
    workspace_id: str, conn: AsyncConnection
) -> list[dict[str, Any]]:
    """Skills routables dans un workspace : grant granted ET placement verified
    ET installed_hash == approved_hash.

    C'est CETTE requête qui matérialise l'invariant de cascade : une révocation
    ou une pause du grant (comme une dérive de hash) fait disparaître le skill
    de l'ensemble effectif à la requête suivante, sans écriture sur placements.
    """
    rows = (
        await conn.execute(
            select(
                skill_placements.c.id.label("placement_id"),
                skill_grants.c.id.label("grant_id"),
                skill_grants.c.user_subject,
                skill_grants.c.skill_id,
                skill_grants.c.approved_hash,
                skill_placements.c.installed_hash,
            )
            .select_from(
                skill_placements.join(
                    skill_grants, skill_placements.c.grant_id == skill_grants.c.id
                )
            )
            .where(skill_placements.c.workspace_id == workspace_id)
            .where(skill_placements.c.statut == "verified")
            .where(skill_grants.c.statut == "granted")
            .where(skill_placements.c.installed_hash == skill_grants.c.approved_hash)
        )
    ).mappings().all()
    return [dict(r) for r in rows]
