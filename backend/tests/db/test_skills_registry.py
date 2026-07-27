"""Registre skills.sh — schéma grants + placements (deux lifecycles liés par FK).

Invariant central testé ici : la révocation (ou pause) d'un grant retire
IMMÉDIATEMENT les placements associés de l'ensemble effectif (la requête de
routage joint grants et placements) — sans toucher aux lignes placements,
conservées pour l'audit.
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from portal.db.skills import (
    approve_grant,
    create_or_get_grant,
    create_or_get_placement,
    delete_placement,
    get_grant,
    list_effective_skills,
    list_grants,
    list_pending_grants,
    list_placements,
    mark_grant_pending,
    pause_grant,
    revoke_grant,
    set_placement_placed,
    set_placement_verified,
)

SUB = "sub-alice"
SKILL = "io.github.owner/repo"
HASH = "sha256:abc123"


async def _granted_verified(conn):
    """Chemin nominal complet : grant validé + placement vérifié, hash concordants."""
    grant, _ = await create_or_get_grant(SUB, SKILL, conn)
    await approve_grant(grant["id"], HASH, conn)
    placement, _ = await create_or_get_placement(grant["id"], "alice-ws", conn)
    await set_placement_placed(placement["id"], HASH, conn)
    await set_placement_verified(placement["id"], True, conn)
    return grant, placement


@pytest.mark.asyncio
async def test_create_grant_pending(db_conn):
    grant, created = await create_or_get_grant(SUB, SKILL, db_conn)
    assert created is True
    assert grant["statut"] == "pending"
    assert grant["approved_hash"] is None


@pytest.mark.asyncio
async def test_create_grant_idempotent(db_conn):
    first, _ = await create_or_get_grant(SUB, SKILL, db_conn)
    second, created = await create_or_get_grant(SUB, SKILL, db_conn)
    assert created is False
    assert second["id"] == first["id"]


@pytest.mark.asyncio
async def test_grants_isolated_by_subject(db_conn):
    await create_or_get_grant(SUB, SKILL, db_conn)
    await create_or_get_grant("sub-bob", SKILL, db_conn)
    assert len(await list_grants(SUB, db_conn)) == 1
    assert (await get_grant("sub-bob", SKILL, db_conn))["statut"] == "pending"


@pytest.mark.asyncio
async def test_approve_sets_hash_and_timestamps(db_conn):
    grant, _ = await create_or_get_grant(SUB, SKILL, db_conn)
    await approve_grant(grant["id"], HASH, db_conn)
    row = await get_grant(SUB, SKILL, db_conn)
    assert row["statut"] == "granted"
    assert row["approved_hash"] == HASH
    assert row["granted_at"] is not None


@pytest.mark.asyncio
async def test_pending_list_includes_hash_drift_revalidation(db_conn):
    """Une dérive de hash retombe en pending SANS perdre l'approved_hash
    (la fiche Validations doit montrer l'ancien hash approuvé vs le nouveau)."""
    grant, _ = await create_or_get_grant(SUB, SKILL, db_conn)
    await approve_grant(grant["id"], HASH, db_conn)
    await mark_grant_pending(grant["id"], db_conn)
    pending = await list_pending_grants(SUB, db_conn)
    assert [g["id"] for g in pending] == [grant["id"]]
    assert pending[0]["approved_hash"] == HASH  # conservé pour comparaison


@pytest.mark.asyncio
async def test_effective_skills_nominal(db_conn):
    grant, placement = await _granted_verified(db_conn)
    effective = await list_effective_skills("alice-ws", db_conn)
    assert len(effective) == 1
    assert effective[0]["skill_id"] == SKILL
    assert effective[0]["user_subject"] == SUB


@pytest.mark.asyncio
async def test_revocation_cuts_effective_set_immediately(db_conn):
    """Invariant : révoquer le grant coupe le routage de TOUS ses placements,
    lignes placements conservées (audit)."""
    grant, _ = await _granted_verified(db_conn)
    p2, _ = await create_or_get_placement(grant["id"], "alice-ws2", db_conn)
    await set_placement_placed(p2["id"], HASH, db_conn)
    await set_placement_verified(p2["id"], True, db_conn)
    assert len(await list_effective_skills("alice-ws", db_conn)) == 1
    assert len(await list_effective_skills("alice-ws2", db_conn)) == 1

    await revoke_grant(grant["id"], db_conn)

    assert await list_effective_skills("alice-ws", db_conn) == []
    assert await list_effective_skills("alice-ws2", db_conn) == []
    # Les placements restent en base pour l'audit.
    assert len(await list_placements("alice-ws", db_conn)) == 1
    row = await get_grant(SUB, SKILL, db_conn)
    assert row["statut"] == "revoked"
    assert row["revoked_at"] is not None


@pytest.mark.asyncio
async def test_pause_cuts_effective_set(db_conn):
    grant, _ = await _granted_verified(db_conn)
    await pause_grant(grant["id"], db_conn)
    assert await list_effective_skills("alice-ws", db_conn) == []


@pytest.mark.asyncio
async def test_hash_mismatch_not_effective(db_conn):
    """installed_hash ≠ approved_hash → jamais routé, même verified."""
    grant, _ = await create_or_get_grant(SUB, SKILL, db_conn)
    await approve_grant(grant["id"], HASH, db_conn)
    placement, _ = await create_or_get_placement(grant["id"], "alice-ws", db_conn)
    await set_placement_placed(placement["id"], "sha256:autre", db_conn)
    await set_placement_verified(placement["id"], True, db_conn)
    assert await list_effective_skills("alice-ws", db_conn) == []


@pytest.mark.asyncio
async def test_unverified_not_effective(db_conn):
    grant, _ = await create_or_get_grant(SUB, SKILL, db_conn)
    await approve_grant(grant["id"], HASH, db_conn)
    placement, _ = await create_or_get_placement(grant["id"], "alice-ws", db_conn)
    await set_placement_placed(placement["id"], HASH, db_conn)
    await set_placement_verified(placement["id"], False, db_conn)  # → unverified
    assert await list_effective_skills("alice-ws", db_conn) == []


@pytest.mark.asyncio
async def test_placement_unique_per_grant_and_workspace(db_conn):
    grant, _ = await create_or_get_grant(SUB, SKILL, db_conn)
    first, created1 = await create_or_get_placement(grant["id"], "alice-ws", db_conn)
    second, created2 = await create_or_get_placement(grant["id"], "alice-ws", db_conn)
    assert created1 is True and created2 is False
    assert second["id"] == first["id"]


@pytest.mark.asyncio
async def test_delete_placement(db_conn):
    grant, placement = await _granted_verified(db_conn)
    assert await delete_placement(placement["id"], db_conn) is True
    assert await list_effective_skills("alice-ws", db_conn) == []
    assert await delete_placement(placement["id"], db_conn) is False


@pytest.mark.asyncio
async def test_invalid_statut_rejected_by_db(db_conn):
    """Le CHECK de statut est un garde-fou DB, pas seulement applicatif."""
    from portal.db.tables import skill_grants

    with pytest.raises(IntegrityError):
        await db_conn.execute(
            skill_grants.insert().values(
                user_subject=SUB, skill_id=SKILL, statut="n-importe-quoi"
            )
        )
