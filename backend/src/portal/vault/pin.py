from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.vault_pin import (
    create_pin_config,
    get_pin_config,
    has_pin_config,
    increment_pin_attempts,
    lock_pin,
    reset_pin_attempts,
    update_pin_config,
)
from ..settings import get_settings
from . import session as vault_session
from .crypto import (
    InvalidKey,
    decrypt_master_key,
    derive_wrap_key,
    encrypt_master_key,
    generate_master_key,
    generate_recovery_code,
    generate_salt,
)

_log = structlog.get_logger(__name__)
_MAX_ATTEMPTS = 5
_LOCK_MINUTES = 15


class PinSetupResult(NamedTuple):
    recovery_code: str


class PinLockedError(Exception):
    def __init__(self, seconds_remaining: float) -> None:
        super().__init__(f"PIN locked for {seconds_remaining:.0f}s")
        self.seconds_remaining = seconds_remaining


class PinWrongError(Exception):
    pass


class PinNotSetupError(Exception):
    pass


def _kek() -> bytes:
    return bytes.fromhex(get_settings().portal_vault_kek)


async def setup_pin(
    login: str, pin: str, session_id: str, conn: AsyncConnection
) -> PinSetupResult:
    if await has_pin_config(login, conn):
        raise ValueError(f"PIN already set for {login!r}")
    master_key = generate_master_key()
    pin_salt = generate_salt()
    wrap_key = derive_wrap_key(pin, pin_salt, _kek())
    enc_mk = encrypt_master_key(master_key, wrap_key)
    recovery_code = generate_recovery_code()
    rec_salt = generate_salt()
    rec_wrap = derive_wrap_key(recovery_code, rec_salt, _kek())
    enc_mk_rec = encrypt_master_key(master_key, rec_wrap)
    await create_pin_config(login, enc_mk, pin_salt, enc_mk_rec, rec_salt, conn)
    vault_session.set_master_key(session_id, master_key)
    _log.info("vault_pin_setup", login=login)
    return PinSetupResult(recovery_code=recovery_code)


async def unlock_pin(
    login: str, pin: str, session_id: str, conn: AsyncConnection
) -> None:
    config = await get_pin_config(login, conn)
    if config is None:
        raise PinNotSetupError(f"No PIN for {login!r}")
    if config["locked_until"] is not None:
        remaining = (config["locked_until"] - datetime.now(UTC)).total_seconds()
        if remaining > 0:
            raise PinLockedError(remaining)
        await reset_pin_attempts(login, conn)
    wrap_key = derive_wrap_key(pin, bytes(config["pin_salt"]), _kek())
    try:
        master_key = decrypt_master_key(bytes(config["encrypted_master_key"]), wrap_key)
    except InvalidKey as exc:
        attempts = await increment_pin_attempts(login, conn)
        if attempts >= _MAX_ATTEMPTS:
            await lock_pin(
                login, datetime.now(UTC) + timedelta(minutes=_LOCK_MINUTES), conn
            )
            _log.warning("vault_pin_locked", login=login)
        raise PinWrongError("Incorrect PIN") from exc
    await reset_pin_attempts(login, conn)
    vault_session.set_master_key(session_id, master_key)
    _log.info("vault_pin_unlocked", login=login)


async def recover_pin(
    login: str,
    recovery_code: str,
    new_pin: str,
    session_id: str,
    conn: AsyncConnection,
) -> PinSetupResult:
    config = await get_pin_config(login, conn)
    if config is None:
        raise PinNotSetupError(f"No PIN for {login!r}")
    rec_wrap = derive_wrap_key(recovery_code, bytes(config["recovery_salt"]), _kek())
    try:
        master_key = decrypt_master_key(
            bytes(config["encrypted_master_key_recovery"]), rec_wrap
        )
    except InvalidKey as exc:
        raise PinWrongError("Incorrect recovery code") from exc
    new_pin_salt = generate_salt()
    new_wrap = derive_wrap_key(new_pin, new_pin_salt, _kek())
    new_enc_mk = encrypt_master_key(master_key, new_wrap)
    new_rec_code = generate_recovery_code()
    new_rec_salt = generate_salt()
    new_rec_wrap = derive_wrap_key(new_rec_code, new_rec_salt, _kek())
    new_enc_mk_rec = encrypt_master_key(master_key, new_rec_wrap)
    await update_pin_config(
        login, new_enc_mk, new_pin_salt, new_enc_mk_rec, new_rec_salt, conn
    )
    vault_session.set_master_key(session_id, master_key)
    _log.info("vault_pin_recovered", login=login)
    return PinSetupResult(recovery_code=new_rec_code)


async def get_vault_status(
    login: str, session_id: str, conn: AsyncConnection
) -> Literal["setup_required", "locked", "unlocked"]:
    if not await has_pin_config(login, conn):
        return "setup_required"
    if vault_session.is_unlocked(session_id):
        return "unlocked"
    return "locked"
