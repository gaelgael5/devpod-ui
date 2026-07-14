"""Délégation agent↔humain : l'agent est un acteur on-behalf-of, jamais un principal.

Invariants testés :
- grants effectifs de l'agent = grants du principal délégant, jamais davantage ;
- révocation de la délégation = kill-switch immédiat, indépendant des grants
  (les grants de l'humain ne bougent pas, et inversement) ;
- expiration = fin de délégation sans action humaine.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from portal.db.delegations import (
    create_or_get_delegation,
    list_agent_effective_skills,
    resolve_principal,
    revoke_delegation,
)
from portal.db.skills import (
    approve_grant,
    create_or_get_grant,
    create_or_get_placement,
    get_grant,
    set_placement_placed,
    set_placement_verified,
)

AGENT = "agent:alice-ws"
SUB = "sub-alice"
SKILL = "io.github.owner/repo"
HASH = "sha256:abc"


async def _skill_ready(conn, subject=SUB, workspace="alice-ws"):
    grant, _ = await create_or_get_grant(subject, SKILL, conn)
    await approve_grant(grant["id"], HASH, conn)
    placement, _ = await create_or_get_placement(grant["id"], workspace, conn)
    await set_placement_placed(placement["id"], HASH, conn)
    await set_placement_verified(placement["id"], True, conn)
    return grant


@pytest.mark.asyncio
async def test_create_and_resolve(db_conn):
    delegation, created = await create_or_get_delegation(AGENT, SUB, db_conn)
    assert created is True
    assert delegation["scope"] == "skills"
    assert await resolve_principal(AGENT, db_conn) == SUB


@pytest.mark.asyncio
async def test_create_idempotent_on_active(db_conn):
    first, _ = await create_or_get_delegation(AGENT, SUB, db_conn)
    second, created = await create_or_get_delegation(AGENT, SUB, db_conn)
    assert created is False
    assert second["id"] == first["id"]


@pytest.mark.asyncio
async def test_no_delegation_resolves_none(db_conn):
    assert await resolve_principal("agent:inconnu", db_conn) is None


@pytest.mark.asyncio
async def test_expired_delegation_resolves_none(db_conn):
    past = datetime.now(UTC) - timedelta(minutes=1)
    await create_or_get_delegation(AGENT, SUB, db_conn, expires_at=past)
    assert await resolve_principal(AGENT, db_conn) is None


@pytest.mark.asyncio
async def test_revoked_delegation_resolves_none(db_conn):
    delegation, _ = await create_or_get_delegation(AGENT, SUB, db_conn)
    assert await revoke_delegation(delegation["id"], db_conn) is True
    assert await resolve_principal(AGENT, db_conn) is None


@pytest.mark.asyncio
async def test_agent_effective_skills_equal_principal_never_more(db_conn):
    """Grants effectifs de l'agent = grants du délégant, jamais davantage :
    le skill effectif d'un AUTRE principal du même workspace n'est pas visible."""
    await _skill_ready(db_conn)  # skill de sub-alice
    await _skill_ready(db_conn, subject="sub-bob", workspace="alice-ws")
    await create_or_get_delegation(AGENT, SUB, db_conn)

    effective = await list_agent_effective_skills(AGENT, "alice-ws", db_conn)
    assert [e["user_subject"] for e in effective] == [SUB]


@pytest.mark.asyncio
async def test_agent_without_delegation_has_nothing(db_conn):
    await _skill_ready(db_conn)
    assert await list_agent_effective_skills(AGENT, "alice-ws", db_conn) == []


@pytest.mark.asyncio
async def test_revocation_is_kill_switch_independent_of_grants(db_conn):
    """Kill-switch : révoquer la délégation coupe le routage de l'agent SANS
    toucher aux grants de l'humain."""
    await _skill_ready(db_conn)
    delegation, _ = await create_or_get_delegation(AGENT, SUB, db_conn)
    assert len(await list_agent_effective_skills(AGENT, "alice-ws", db_conn)) == 1

    await revoke_delegation(delegation["id"], db_conn)

    assert await list_agent_effective_skills(AGENT, "alice-ws", db_conn) == []
    # Les grants du principal sont intacts.
    assert (await get_grant(SUB, SKILL, db_conn))["statut"] == "granted"


@pytest.mark.asyncio
async def test_regrant_after_revocation_possible(db_conn):
    """Après révocation, une NOUVELLE délégation (action humaine) est possible —
    l'index unique ne porte que sur les délégations actives."""
    first, _ = await create_or_get_delegation(AGENT, SUB, db_conn)
    await revoke_delegation(first["id"], db_conn)
    second, created = await create_or_get_delegation(AGENT, SUB, db_conn)
    assert created is True
    assert second["id"] != first["id"]
    assert await resolve_principal(AGENT, db_conn) == SUB
