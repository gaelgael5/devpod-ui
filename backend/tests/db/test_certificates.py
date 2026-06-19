from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.certificates import (
    create_certificate,
    delete_certificate,
    get_private_key_local,
    list_certificates,
    set_public,
)
from portal.db.tables import users

pytestmark = pytest.mark.asyncio

_PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 test"
_PRIV = b"\xAB" * 64


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def test_create_and_list(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await create_certificate(
        "alice", "gh-key", "GitHub", "", "ssh-ed25519", _PUB,
        private_key_local=_PRIV, private_key_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    rows = await list_certificates("alice", db_conn)
    assert len(rows) == 1
    assert rows[0]["slug"] == "gh-key"
    assert "private_key_local" not in rows[0]


async def test_list_includes_public_from_other_user(db_conn: AsyncConnection) -> None:
    await _user(db_conn, "alice")
    await _user(db_conn, "bob")
    await create_certificate(
        "bob", "shared", "Shared", "", "ssh-ed25519", _PUB,
        private_key_local=_PRIV, private_key_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    await set_public("shared", True, db_conn)
    rows = await list_certificates("alice", db_conn)
    assert any(r["slug"] == "shared" for r in rows)


async def test_get_private_key(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await create_certificate(
        "alice", "k1", "K1", "", "ssh-ed25519", _PUB,
        private_key_local=_PRIV, private_key_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    blob = await get_private_key_local("alice", "k1", db_conn)
    assert blob == _PRIV


async def test_get_private_key_public_cert_denied(db_conn: AsyncConnection) -> None:
    await _user(db_conn, "alice")
    await _user(db_conn, "bob")
    await create_certificate(
        "bob", "shared", "S", "", "ssh-ed25519", _PUB,
        private_key_local=_PRIV, private_key_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    await set_public("shared", True, db_conn)
    # alice ne peut pas récupérer la clé privée locale d'un cert public qui ne lui appartient pas
    blob = await get_private_key_local("alice", "shared", db_conn)
    assert blob is None


async def test_delete_returns_row(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    await create_certificate(
        "alice", "k1", "K1", "", "ssh-ed25519", _PUB,
        private_key_local=_PRIV, private_key_vault_ref=None,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    row = await delete_certificate("alice", "k1", db_conn)
    assert row is not None
    assert row["slug"] == "k1"
    assert await list_certificates("alice", db_conn) == []


async def test_delete_nonexistent_returns_none(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    assert await delete_certificate("alice", "ghost", db_conn) is None
