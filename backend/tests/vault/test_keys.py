from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from portal.vault import session as vault_session
from portal.vault.keys import (
    KeyAlreadyExists,
    KeyNotFound,
    VaultLocked,
    add_key,
    delete_key,
    list_keys,
)

pytestmark = pytest.mark.asyncio

_SID = "keys-session"
_MK = b"k" * 32
_TOKEN = "hrpv_1_test"
_URL = "https://vault.yoops.org"


@pytest.fixture(autouse=True)
def session():
    vault_session.set_master_key(_SID, _MK)
    yield
    vault_session.clear_session(_SID)


@pytest.fixture
def conn():
    return AsyncMock()


async def test_add_vault_locked_raises(conn):
    vault_session.clear_session(_SID)
    with pytest.raises(VaultLocked):
        await add_key("alice", _SID, "api1", _TOKEN, _URL, "", conn)


async def test_add_key_success(conn):
    with (
        patch("portal.vault.keys.vault_key_exists", new=AsyncMock(return_value=False)),
        patch("portal.vault.keys.create_vault_key", new=AsyncMock()),
    ):
        await add_key("alice", _SID, "api1", _TOKEN, _URL, "", conn)


async def test_add_key_exists_raises(conn):
    with patch("portal.vault.keys.vault_key_exists", new=AsyncMock(return_value=True)):
        with pytest.raises(KeyAlreadyExists):
            await add_key("alice", _SID, "api1", _TOKEN, _URL, "", conn)


async def test_list_keys(conn):
    with patch(
        "portal.vault.keys.list_vault_keys",
        new=AsyncMock(
            return_value=[{"identifier": "api1", "url": _URL, "description": ""}]
        ),
    ):
        result = await list_keys("alice", conn)
    assert result[0]["identifier"] == "api1"


async def test_delete_not_found_raises(conn):
    with patch("portal.vault.keys.delete_vault_key", new=AsyncMock(return_value=False)):
        with pytest.raises(KeyNotFound):
            await delete_key("alice", _SID, "ghost", conn)


async def test_delete_success(conn):
    with patch("portal.vault.keys.delete_vault_key", new=AsyncMock(return_value=True)):
        await delete_key("alice", _SID, "api1", conn)
