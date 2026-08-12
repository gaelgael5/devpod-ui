"""Portée user→host SSH (spec 18 T3) : N-N `user_host_grant`.

DB réelle (SAVEPOINT `db_conn`). Skippés sans Docker ; tournent sur Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db import user_host_grant as g
from portal.db.tables import users, workspace_status
from portal.db.workspace_status import list_ssh_hosts_db


async def _mk_user(conn: AsyncConnection, login: str) -> None:
    await conn.execute(users.insert().values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def _mk_host(conn: AsyncConnection, ws_id: str, login: str, ssh_port: int | None) -> None:
    await conn.execute(
        workspace_status.insert().values(
            ws_id=ws_id, status="running", login=login, ssh_port=ssh_port, host_name="node1"
        )
    )


@pytest.mark.asyncio
async def test_grant_revoke_and_lists(db_conn: AsyncConnection) -> None:
    await _mk_user(db_conn, "alice")
    await _mk_host(db_conn, "ws-a", "alice", 50001)
    await _mk_host(db_conn, "ws-b", "alice", 50002)

    await g.grant(db_conn, "alice", "ws-a")
    await g.grant(db_conn, "alice", "ws-a")  # idempotent
    await g.grant(db_conn, "alice", "ws-b")
    assert await g.list_hosts_for_user(db_conn, "alice") == ["ws-a", "ws-b"]
    assert await g.list_users_for_host(db_conn, "ws-a") == ["alice"]
    assert await g.is_granted(db_conn, "alice", "ws-a") is True

    assert await g.revoke(db_conn, "alice", "ws-a") is True
    assert await g.revoke(db_conn, "alice", "ws-a") is False
    assert await g.list_hosts_for_user(db_conn, "alice") == ["ws-b"]


@pytest.mark.asyncio
async def test_set_hosts_replaces(db_conn: AsyncConnection) -> None:
    await _mk_user(db_conn, "bob")
    for w in ("ws-1", "ws-2", "ws-3"):
        await _mk_host(db_conn, w, "bob", 50000 + int(w[-1]))
    await g.set_hosts_for_user(db_conn, "bob", ["ws-1", "ws-2"])
    assert await g.list_hosts_for_user(db_conn, "bob") == ["ws-1", "ws-2"]
    # Remplacement : retire ws-1, ajoute ws-3.
    await g.set_hosts_for_user(db_conn, "bob", ["ws-2", "ws-3"])
    assert await g.list_hosts_for_user(db_conn, "bob") == ["ws-2", "ws-3"]
    await g.set_hosts_for_user(db_conn, "bob", [])
    assert await g.list_hosts_for_user(db_conn, "bob") == []


@pytest.mark.asyncio
async def test_ssh_hosts_universe_only_published(db_conn: AsyncConnection) -> None:
    await _mk_user(db_conn, "carol")
    await _mk_host(db_conn, "pub", "carol", 50010)
    await _mk_host(db_conn, "unpub", "carol", None)  # pas de ssh_port → hors univers
    hosts = await list_ssh_hosts_db(db_conn)
    ws_ids = [h["ws_id"] for h in hosts]
    assert "pub" in ws_ids
    assert "unpub" not in ws_ids
    row = next(h for h in hosts if h["ws_id"] == "pub")
    assert row["login"] == "carol" and row["ssh_port"] == 50010 and row["host_name"] == "node1"


@pytest.mark.asyncio
async def test_cascade_on_host_delete(db_conn: AsyncConnection) -> None:
    await _mk_user(db_conn, "dave")
    await _mk_host(db_conn, "ws-x", "dave", 50020)
    await g.grant(db_conn, "dave", "ws-x")
    await db_conn.execute(workspace_status.delete().where(workspace_status.c.ws_id == "ws-x"))
    assert await g.list_hosts_for_user(db_conn, "dave") == []
