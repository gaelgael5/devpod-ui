from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.tables import users
from portal.db.vault_pin import (
    create_pin_config,
    get_pin_config,
    has_pin_config,
    increment_pin_attempts,
    lock_pin,
    reset_pin_attempts,
    update_pin_config,
)

pytestmark = pytest.mark.asyncio

_ENC_MK = b"\x01" * 44
_SALT = b"\x02" * 16
_ENC_REC = b"\x03" * 44
_REC_SALT = b"\x04" * 16


async def _user(conn: AsyncConnection, login: str = "alice") -> None:
    await conn.execute(
        insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4()))
    )


async def test_has_pin_false_before_setup(db_conn):
    await _user(db_conn)
    assert await has_pin_config("alice", db_conn) is False


async def test_create_and_get(db_conn):
    await _user(db_conn)
    await create_pin_config("alice", _ENC_MK, _SALT, _ENC_REC, _REC_SALT, db_conn)
    row = await get_pin_config("alice", db_conn)
    assert row is not None
    assert bytes(row["encrypted_master_key"]) == _ENC_MK
    assert row["pin_attempts"] == 0


async def test_has_pin_true_after_create(db_conn):
    await _user(db_conn)
    await create_pin_config("alice", _ENC_MK, _SALT, _ENC_REC, _REC_SALT, db_conn)
    assert await has_pin_config("alice", db_conn) is True


async def test_increment_attempts(db_conn):
    await _user(db_conn)
    await create_pin_config("alice", _ENC_MK, _SALT, _ENC_REC, _REC_SALT, db_conn)
    assert await increment_pin_attempts("alice", db_conn) == 1
    assert await increment_pin_attempts("alice", db_conn) == 2


async def test_reset_attempts(db_conn):
    await _user(db_conn)
    await create_pin_config("alice", _ENC_MK, _SALT, _ENC_REC, _REC_SALT, db_conn)
    await increment_pin_attempts("alice", db_conn)
    await reset_pin_attempts("alice", db_conn)
    row = await get_pin_config("alice", db_conn)
    assert row["pin_attempts"] == 0


async def test_lock_pin(db_conn):
    await _user(db_conn)
    await create_pin_config("alice", _ENC_MK, _SALT, _ENC_REC, _REC_SALT, db_conn)
    until = datetime.now(UTC) + timedelta(minutes=15)
    await lock_pin("alice", until, db_conn)
    row = await get_pin_config("alice", db_conn)
    assert row["locked_until"] is not None


async def test_update_pin_config(db_conn):
    await _user(db_conn)
    await create_pin_config("alice", _ENC_MK, _SALT, _ENC_REC, _REC_SALT, db_conn)
    new_mk = b"\x05" * 44
    await update_pin_config("alice", new_mk, _SALT, _ENC_REC, _REC_SALT, db_conn)
    row = await get_pin_config("alice", db_conn)
    assert bytes(row["encrypted_master_key"]) == new_mk
