from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.certificates.service import (
    CertAlreadyExists,
    CertNotFound,
    VaultLocked,
    generate_and_register,
    list_user_certificates,
    register_certificate,
    remove_certificate,
    reveal_private_key,
)
from portal.db.tables import users
from portal.vault import session as vault_session

pytestmark = pytest.mark.asyncio

_PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 test"
_PRIV = "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n"
_SID = "test-session-123"
_MASTER = b"\x01" * 32


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4())))


async def test_register_local_and_list(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_certificate(
        "alice", _SID, "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    certs = await list_user_certificates("alice", db_conn)
    assert len(certs) == 1
    assert certs[0]["slug"] == "gh"
    assert "private_key_local" not in certs[0]


async def test_register_duplicate_raises(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_certificate(
        "alice", _SID, "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    with pytest.raises(CertAlreadyExists):
        await register_certificate(
            "alice", _SID, "gh", "GitHub2", "", "ssh-ed25519", _PUB, _PRIV,
            storage_type="local", vault_identifier=None, conn=db_conn,
        )


async def test_register_vault_locked_raises(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.clear_session("no-session")
    with pytest.raises(VaultLocked):
        await register_certificate(
            "alice", "no-session", "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
            storage_type="local", vault_identifier=None, conn=db_conn,
        )


async def test_reveal_private_key(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_certificate(
        "alice", _SID, "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    plain = await reveal_private_key("alice", _SID, "gh", db_conn)
    assert plain == _PRIV


async def test_reveal_vault_locked(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_certificate(
        "alice", _SID, "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    vault_session.clear_session(_SID)
    with pytest.raises(VaultLocked):
        await reveal_private_key("alice", _SID, "gh", db_conn)


async def test_generate_and_register(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    pub = await generate_and_register(
        "alice", _SID, "new-key", "New Key", "", "ssh-ed25519",
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    assert pub.startswith("ssh-ed25519")
    certs = await list_user_certificates("alice", db_conn)
    assert certs[0]["slug"] == "new-key"


async def test_remove_certificate(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    await register_certificate(
        "alice", _SID, "gh", "GitHub", "", "ssh-ed25519", _PUB, _PRIV,
        storage_type="local", vault_identifier=None, conn=db_conn,
    )
    await remove_certificate("alice", _SID, "gh", db_conn)
    assert await list_user_certificates("alice", db_conn) == []


async def test_remove_nonexistent_raises(db_conn: AsyncConnection) -> None:
    await _user(db_conn)
    vault_session.set_master_key(_SID, _MASTER)
    with pytest.raises(CertNotFound):
        await remove_certificate("alice", _SID, "ghost", db_conn)
