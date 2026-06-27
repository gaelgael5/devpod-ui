from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.tables import users
from portal.db.vault_keys import (
    create_vault_key,
    delete_vault_key,
    get_encrypted_token,
    list_vault_keys,
    vault_key_exists,
)

pytestmark = pytest.mark.asyncio

_TOKEN = b"\xAB" * 60
_URL = "https://vault.yoops.org"


async def _user(conn: AsyncConnection, login: str = "bob") -> None:
    await conn.execute(
        insert(users).values(login=login, version="1", secret_ns=str(uuid.uuid4()))
    )


async def test_create_and_list(db_conn):
    await _user(db_conn)
    await create_vault_key("bob", "api1", _TOKEN, _URL, "prod", db_conn)
    keys = await list_vault_keys("bob", db_conn)
    assert len(keys) == 1
    assert keys[0]["identifier"] == "api1"
    assert "encrypted_token" not in keys[0]


async def test_get_encrypted_token(db_conn):
    await _user(db_conn)
    await create_vault_key("bob", "api1", _TOKEN, _URL, "", db_conn)
    assert await get_encrypted_token("bob", "api1", db_conn) == _TOKEN


async def test_get_unknown_returns_none(db_conn):
    await _user(db_conn)
    assert await get_encrypted_token("bob", "ghost", db_conn) is None


async def test_delete_returns_true(db_conn):
    await _user(db_conn)
    await create_vault_key("bob", "api1", _TOKEN, _URL, "", db_conn)
    assert await delete_vault_key("bob", "api1", db_conn) is True
    assert await list_vault_keys("bob", db_conn) == []


async def test_delete_nonexistent_returns_false(db_conn):
    await _user(db_conn)
    assert await delete_vault_key("bob", "ghost", db_conn) is False


async def test_vault_key_exists(db_conn):
    await _user(db_conn)
    assert await vault_key_exists("bob", "api1", db_conn) is False
    await create_vault_key("bob", "api1", _TOKEN, _URL, "", db_conn)
    assert await vault_key_exists("bob", "api1", db_conn) is True
