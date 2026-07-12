"""Spec 35 §8.3 — cycle de vie des clefs API par workspace × profil exposé."""

from __future__ import annotations

import uuid

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.agents.keys import (
    revoke_profile_workspace_keys,
    revoke_workspace_keys,
    rotate_workspace_keys,
)
from portal.db.mcp import find_apikey_by_hash, list_apikeys
from portal.db.mcp_profiles import insert_profile, set_profile_exposed
from portal.db.tables import users
from portal.mcp.service import token_hash


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def _exposed_profile(
    conn: AsyncConnection, login: str, pid: str, name: str | None = None
) -> None:
    await insert_profile(conn, id=pid, owner_login=login, name=name or pid)
    await set_profile_exposed(conn, login, pid, exposed=True)


async def test_rotate_creates_one_key_per_exposed_profile(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _exposed_profile(db_conn, "alice", "p1", "lecture")
    await insert_profile(db_conn, id="p2", owner_login="alice", name="non exposé")

    keys = await rotate_workspace_keys(db_conn, "alice", "alice-api")
    assert len(keys) == 1
    k = keys[0]
    assert k.profile_id == "p1"
    assert k.profile_name == "lecture"
    assert k.token.startswith("mcpk_")

    row = await find_apikey_by_hash(db_conn, token_hash(k.token))
    assert row is not None
    assert row["workspace_ref"] == "alice-api"
    assert row["profile_id"] == "p1"
    assert row["label"] == "ws:alice-api/lecture"


async def test_rotate_revokes_previous_generation(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _exposed_profile(db_conn, "alice", "p1")

    gen1 = await rotate_workspace_keys(db_conn, "alice", "alice-api")
    gen2 = await rotate_workspace_keys(db_conn, "alice", "alice-api")

    assert await find_apikey_by_hash(db_conn, token_hash(gen1[0].token)) is None
    assert await find_apikey_by_hash(db_conn, token_hash(gen2[0].token)) is not None


async def test_rotate_without_exposed_profiles_revokes_and_returns_empty(
    db_conn: AsyncConnection,
) -> None:
    await _user(db_conn)
    await _exposed_profile(db_conn, "alice", "p1")
    gen1 = await rotate_workspace_keys(db_conn, "alice", "alice-api")

    await set_profile_exposed(db_conn, "alice", "p1", exposed=False)
    keys = await rotate_workspace_keys(db_conn, "alice", "alice-api")
    assert keys == []
    assert await find_apikey_by_hash(db_conn, token_hash(gen1[0].token)) is None


async def test_revoke_workspace_keys(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _exposed_profile(db_conn, "alice", "p1")
    await _exposed_profile(db_conn, "alice", "p2")
    keys = await rotate_workspace_keys(db_conn, "alice", "alice-api")
    assert len(keys) == 2

    n = await revoke_workspace_keys(db_conn, "alice", "alice-api")
    assert n == 2
    for k in keys:
        assert await find_apikey_by_hash(db_conn, token_hash(k.token)) is None


async def test_revoke_profile_keys_scoped(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _exposed_profile(db_conn, "alice", "p1")
    await _exposed_profile(db_conn, "alice", "p2")
    ws1 = await rotate_workspace_keys(db_conn, "alice", "alice-api")
    ws2 = await rotate_workspace_keys(db_conn, "alice", "alice-front")

    affected = await revoke_profile_workspace_keys(db_conn, "alice", "p1")
    assert sorted(affected) == ["alice-api", "alice-front"]

    for keys in (ws1, ws2):
        by_pid = {k.profile_id: k for k in keys}
        assert await find_apikey_by_hash(db_conn, token_hash(by_pid["p1"].token)) is None
        assert await find_apikey_by_hash(db_conn, token_hash(by_pid["p2"].token)) is not None


async def test_revoke_profile_keys_ignores_personal_keys(db_conn: AsyncConnection) -> None:
    from portal.mcp.models import ApikeyCreate
    from portal.mcp.service import create_apikey

    await _user(db_conn)
    await _exposed_profile(db_conn, "alice", "p1")
    _, personal = await create_apikey(
        db_conn, "alice", ApikeyCreate(label="perso", profile_id="p1")
    )
    await rotate_workspace_keys(db_conn, "alice", "alice-api")

    await revoke_profile_workspace_keys(db_conn, "alice", "p1")
    assert await find_apikey_by_hash(db_conn, token_hash(personal)) is not None


async def test_isolation_between_owners(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await _user(db_conn, "bob")
    await _exposed_profile(db_conn, "alice", "pa")
    await _exposed_profile(db_conn, "bob", "pb")
    ka = await rotate_workspace_keys(db_conn, "alice", "alice-api")
    kb = await rotate_workspace_keys(db_conn, "bob", "bob-api")

    # révocations de bob sans effet sur alice
    await revoke_workspace_keys(db_conn, "bob", "alice-api")
    await revoke_profile_workspace_keys(db_conn, "bob", "pa")
    assert await find_apikey_by_hash(db_conn, token_hash(ka[0].token)) is not None
    assert await find_apikey_by_hash(db_conn, token_hash(kb[0].token)) is not None

    # les clefs de bob restent listées sous bob uniquement
    assert all(r["owner_login"] == "alice" for r in await list_apikeys(db_conn, "alice"))
