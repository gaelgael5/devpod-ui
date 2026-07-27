"""Délégation agent↔humain (table agent_delegations).

L'agent est un acteur on-behalf-of exactement un humain, jamais un principal
autonome. Tout check d'autorisation passe par ``resolve_principal`` — même en
v1 single-principal où la résolution est triviale — pour rouvrir le
multi-principal sans réécriture. L'audit des appels enregistre les deux
identités (agent + principal) aux points d'appel.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import agent_delegations, skill_grants, skill_placements

DEFAULT_SCOPE = "skills"


def _active_clause() -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    """Délégation active : non révoquée et non expirée (horloge DB)."""
    return (
        agent_delegations.c.revoked_at.is_(None),
        or_(
            agent_delegations.c.expires_at.is_(None),
            agent_delegations.c.expires_at > func.now(),
        ),
    )


async def create_or_get_delegation(
    agent_id: str,
    principal_subject: str,
    conn: AsyncConnection,
    scope: str = DEFAULT_SCOPE,
    expires_at: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Crée la délégation (action humaine). Idempotent : si une délégation
    ACTIVE existe déjà pour (agent, scope), elle est retournée telle quelle —
    y compris si elle pointe un autre principal (la remplacer = révoquer
    d'abord, décision humaine explicite)."""
    existing = (
        await conn.execute(
            select(agent_delegations)
            .where(agent_delegations.c.agent_id == agent_id)
            .where(agent_delegations.c.scope == scope)
            .where(*_active_clause())
        )
    ).mappings().one_or_none()
    if existing is not None:
        return dict(existing), False
    row = (
        await conn.execute(
            agent_delegations.insert()
            .values(
                agent_id=agent_id,
                principal_subject=principal_subject,
                scope=scope,
                expires_at=expires_at,
            )
            .returning(agent_delegations)
        )
    ).mappings().one()
    return dict(row), True


async def resolve_principal(
    agent_id: str, conn: AsyncConnection, scope: str = DEFAULT_SCOPE
) -> str | None:
    """Résout l'agent vers son principal délégant. None = aucun droit (fail
    closed) : pas de délégation, expirée ou révoquée."""
    row = (
        await conn.execute(
            select(agent_delegations.c.principal_subject)
            .where(agent_delegations.c.agent_id == agent_id)
            .where(agent_delegations.c.scope == scope)
            .where(*_active_clause())
        )
    ).scalar_one_or_none()
    return row


async def revoke_delegation(delegation_id: int, conn: AsyncConnection) -> bool:
    """Kill-switch : coupe le routage de l'agent SANS toucher aux grants du
    principal (et réciproquement). Ligne conservée pour l'audit."""
    result = await conn.execute(
        update(agent_delegations)
        .where(agent_delegations.c.id == delegation_id)
        .where(agent_delegations.c.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    return (result.rowcount or 0) > 0


async def list_delegations(
    principal_subject: str, conn: AsyncConnection
) -> list[dict[str, Any]]:
    """Toutes les délégations émises par un humain (actives et passées — audit)."""
    rows = (
        await conn.execute(
            select(agent_delegations)
            .where(agent_delegations.c.principal_subject == principal_subject)
            .order_by(agent_delegations.c.id)
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def list_agent_effective_skills(
    agent_id: str,
    workspace_id: str,
    conn: AsyncConnection,
    scope: str = DEFAULT_SCOPE,
) -> list[dict[str, Any]]:
    """Skills routables pour un AGENT dans un workspace.

    = ensemble effectif du principal délégant (grant granted ∧ placement
    verified ∧ hash concordants), restreint à SES grants — jamais davantage.
    Sans délégation valide : ensemble vide (fail closed).
    """
    principal = await resolve_principal(agent_id, conn, scope)
    if principal is None:
        return []
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
            .where(skill_grants.c.user_subject == principal)
        )
    ).mappings().all()
    return [dict(r) for r in rows]
