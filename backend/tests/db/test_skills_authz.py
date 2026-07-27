"""Décision de routage des skills (portal.skills.authz) — les deux kill-switches.

Vérifie de bout en bout, sur DB réelle, que la double condition (grant granted
+ placement verified + hash concordant) ET (délégation valide) gouverne le
routage, et que chacune coupe indépendamment.
"""
from __future__ import annotations

import pytest

from portal.db.delegations import create_or_get_delegation, revoke_delegation
from portal.db.skills import (
    approve_grant,
    create_or_get_grant,
    create_or_get_placement,
    pause_grant,
    revoke_grant,
    set_placement_placed,
    set_placement_verified,
)
from portal.skills.authz import is_skill_routable, list_routable_skills

AGENT = "agent:alice-ws"
SUB = "sub-alice"
WS = "alice-ws"
SKILL = "github/awesome-copilot/git-commit"
HASH = "sha256:approved"


async def _fully_wired(db_conn, installed_hash=HASH, verify=True):
    """Grant granted + placement placed/verified + délégation active."""
    grant, _ = await create_or_get_grant(SUB, SKILL, db_conn)
    await approve_grant(grant["id"], HASH, db_conn)
    placement, _ = await create_or_get_placement(grant["id"], WS, db_conn)
    await set_placement_placed(placement["id"], installed_hash, db_conn)
    await set_placement_verified(placement["id"], verify, db_conn)
    delegation, _ = await create_or_get_delegation(AGENT, SUB, db_conn)
    return grant, placement, delegation


@pytest.mark.asyncio
async def test_routable_when_all_conditions_met(db_conn):
    await _fully_wired(db_conn)
    assert await is_skill_routable(AGENT, WS, SKILL, db_conn) is True
    routable = await list_routable_skills(AGENT, WS, db_conn)
    assert [r["skill_id"] for r in routable] == [SKILL]


@pytest.mark.asyncio
async def test_grant_revocation_cuts_routing(db_conn):
    grant, _, _ = await _fully_wired(db_conn)
    await revoke_grant(grant["id"], db_conn)
    assert await is_skill_routable(AGENT, WS, SKILL, db_conn) is False


@pytest.mark.asyncio
async def test_grant_pause_cuts_routing(db_conn):
    grant, _, _ = await _fully_wired(db_conn)
    await pause_grant(grant["id"], db_conn)
    assert await is_skill_routable(AGENT, WS, SKILL, db_conn) is False


@pytest.mark.asyncio
async def test_delegation_revocation_cuts_routing_independently(db_conn):
    """Kill-switch #2 : révoquer la délégation coupe le routage sans toucher au
    grant (qui reste granted)."""
    grant, _, delegation = await _fully_wired(db_conn)
    await revoke_delegation(delegation["id"], db_conn)
    assert await is_skill_routable(AGENT, WS, SKILL, db_conn) is False
    assert await list_routable_skills(AGENT, WS, db_conn) == []


@pytest.mark.asyncio
async def test_unverified_placement_not_routable(db_conn):
    await _fully_wired(db_conn, verify=False)
    assert await is_skill_routable(AGENT, WS, SKILL, db_conn) is False


@pytest.mark.asyncio
async def test_hash_drift_not_routable(db_conn):
    await _fully_wired(db_conn, installed_hash="sha256:drifted")
    assert await is_skill_routable(AGENT, WS, SKILL, db_conn) is False


@pytest.mark.asyncio
async def test_no_delegation_fails_closed(db_conn):
    """Sans délégation : refus, même grant+placement parfaits."""
    grant, _ = await create_or_get_grant(SUB, SKILL, db_conn)
    await approve_grant(grant["id"], HASH, db_conn)
    placement, _ = await create_or_get_placement(grant["id"], WS, db_conn)
    await set_placement_placed(placement["id"], HASH, db_conn)
    await set_placement_verified(placement["id"], True, db_conn)
    assert await is_skill_routable(AGENT, WS, SKILL, db_conn) is False


@pytest.mark.asyncio
async def test_other_skill_not_routable(db_conn):
    await _fully_wired(db_conn)
    assert await is_skill_routable(AGENT, WS, "other/skill", db_conn) is False


@pytest.mark.asyncio
async def test_other_workspace_not_routable(db_conn):
    """Le placement est per-workspace : routable dans WS, pas ailleurs."""
    await _fully_wired(db_conn)
    assert await is_skill_routable(AGENT, "alice-autre", SKILL, db_conn) is False
