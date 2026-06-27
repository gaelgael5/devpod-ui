from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from portal.vault import session as vault_session
from portal.vault.pin import (
    PinLockedError,
    PinNotSetupError,
    PinSetupResult,
    PinWrongError,
    get_vault_status,
    recover_pin,
    setup_pin,
    unlock_pin,
)

pytestmark = pytest.mark.asyncio

_KEK_HEX = "a" * 64
_PIN = "123456"
_SID = "test-session"


@pytest.fixture(autouse=True)
def clean_session():
    vault_session.clear_session(_SID)
    yield
    vault_session.clear_session(_SID)


@pytest.fixture
def conn():
    return AsyncMock()


@pytest.fixture(autouse=True)
def patch_kek(monkeypatch):
    s = MagicMock()
    s.portal_vault_kek = _KEK_HEX
    monkeypatch.setattr("portal.vault.pin.get_settings", lambda: s)


async def test_setup_returns_recovery_code(conn):
    with (
        patch("portal.vault.pin.has_pin_config", new=AsyncMock(return_value=False)),
        patch("portal.vault.pin.create_pin_config", new=AsyncMock()),
    ):
        result = await setup_pin("alice", _PIN, _SID, conn)
    assert isinstance(result, PinSetupResult)
    parts = result.recovery_code.split("-")
    assert len(parts) == 6 and all(len(p) == 4 for p in parts)
    assert vault_session.is_unlocked(_SID)


async def test_setup_already_exists_raises(conn):
    with patch("portal.vault.pin.has_pin_config", new=AsyncMock(return_value=True)):
        with pytest.raises(ValueError, match="already"):
            await setup_pin("alice", _PIN, _SID, conn)


async def test_unlock_success(conn):
    from portal.vault.crypto import (
        derive_wrap_key,
        encrypt_master_key,
        generate_master_key,
        generate_salt,
    )

    mk = generate_master_key()
    salt = generate_salt()
    kek = bytes.fromhex(_KEK_HEX)
    wk = derive_wrap_key(_PIN, salt, kek)
    enc = encrypt_master_key(mk, wk)
    config = {
        "encrypted_master_key": enc,
        "pin_salt": salt,
        "pin_attempts": 0,
        "locked_until": None,
    }
    with (
        patch("portal.vault.pin.get_pin_config", new=AsyncMock(return_value=config)),
        patch("portal.vault.pin.reset_pin_attempts", new=AsyncMock()),
    ):
        await unlock_pin("alice", _PIN, _SID, conn)
    assert vault_session.is_unlocked(_SID)


async def test_unlock_wrong_pin_raises(conn):
    from portal.vault.crypto import (
        derive_wrap_key,
        encrypt_master_key,
        generate_master_key,
        generate_salt,
    )

    mk = generate_master_key()
    salt = generate_salt()
    kek = bytes.fromhex(_KEK_HEX)
    wk = derive_wrap_key(_PIN, salt, kek)
    enc = encrypt_master_key(mk, wk)
    config = {
        "encrypted_master_key": enc,
        "pin_salt": salt,
        "pin_attempts": 0,
        "locked_until": None,
    }
    with (
        patch("portal.vault.pin.get_pin_config", new=AsyncMock(return_value=config)),
        patch("portal.vault.pin.increment_pin_attempts", new=AsyncMock(return_value=1)),
    ):
        with pytest.raises(PinWrongError):
            await unlock_pin("alice", "000000", _SID, conn)
    assert not vault_session.is_unlocked(_SID)


async def test_get_vault_status_setup_required(conn):
    with patch("portal.vault.pin.has_pin_config", new=AsyncMock(return_value=False)):
        assert await get_vault_status("alice", _SID, conn) == "setup_required"


async def test_get_vault_status_unlocked(conn):
    vault_session.set_master_key(_SID, b"x" * 32)
    with patch("portal.vault.pin.has_pin_config", new=AsyncMock(return_value=True)):
        assert await get_vault_status("alice", _SID, conn) == "unlocked"


async def test_get_vault_status_locked(conn):
    with patch("portal.vault.pin.has_pin_config", new=AsyncMock(return_value=True)):
        assert await get_vault_status("alice", _SID, conn) == "locked"
