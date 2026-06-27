"""Tests de la couche DB workspace_ssh_keys (Tour 8)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.ssh_keys import delete_ssh_key_db, get_ssh_key_db, upsert_ssh_key_db

pytestmark = pytest.mark.asyncio

_PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA devpod:alice/my-ws"
_PRIV_PATH = "/data/users/alice/keys/workspaces/my-ws/id_ed25519"


async def _seed_workspace(conn: AsyncConnection, login: str = "alice", name: str = "my-ws") -> None:
    ns = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO users (login, version, secret_ns) VALUES (:l, '1', :ns)"
            " ON CONFLICT DO NOTHING"
        ),
        {"l": login, "ns": ns},
    )
    await conn.execute(
        text(
            "INSERT INTO workspaces (login, name, source)"
            " VALUES (:l, :n, 'https://github.com/test/repo')"
            " ON CONFLICT DO NOTHING"
        ),
        {"l": login, "n": name},
    )


async def test_upsert_and_get(db_conn: AsyncConnection) -> None:
    await _seed_workspace(db_conn)
    await upsert_ssh_key_db("alice", "my-ws", _PRIV_PATH, _PUB, db_conn)
    result = await get_ssh_key_db("alice", "my-ws", db_conn)
    assert result == _PUB


async def test_get_unknown_returns_none(db_conn: AsyncConnection) -> None:
    result = await get_ssh_key_db("alice", "ghost-ws", db_conn)
    assert result is None


async def test_upsert_updates_public_key(db_conn: AsyncConnection) -> None:
    await _seed_workspace(db_conn)
    await upsert_ssh_key_db("alice", "my-ws", _PRIV_PATH, _PUB, db_conn)
    new_pub = "ssh-ed25519 BBBBC3NzaC1lZDI1NTE5BBBB devpod:alice/my-ws"
    await upsert_ssh_key_db("alice", "my-ws", _PRIV_PATH, new_pub, db_conn)
    result = await get_ssh_key_db("alice", "my-ws", db_conn)
    assert result == new_pub


async def test_delete(db_conn: AsyncConnection) -> None:
    await _seed_workspace(db_conn)
    await upsert_ssh_key_db("alice", "my-ws", _PRIV_PATH, _PUB, db_conn)
    await delete_ssh_key_db("alice", "my-ws", db_conn)
    result = await get_ssh_key_db("alice", "my-ws", db_conn)
    assert result is None


async def test_delete_nonexistent_no_error(db_conn: AsyncConnection) -> None:
    await delete_ssh_key_db("alice", "ghost-ws", db_conn)


async def test_isolation_between_users(db_conn: AsyncConnection) -> None:
    await _seed_workspace(db_conn, "alice", "my-ws")
    await _seed_workspace(db_conn, "bob", "my-ws")
    alice_pub = "ssh-ed25519 AAAA devpod:alice/my-ws"
    bob_pub = "ssh-ed25519 BBBB devpod:bob/my-ws"
    await upsert_ssh_key_db("alice", "my-ws", _PRIV_PATH, alice_pub, db_conn)
    await upsert_ssh_key_db("bob", "my-ws", "/data/bob/...", bob_pub, db_conn)

    assert await get_ssh_key_db("alice", "my-ws", db_conn) == alice_pub
    assert await get_ssh_key_db("bob", "my-ws", db_conn) == bob_pub
