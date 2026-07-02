from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db.user_config import ensure_user_db
from ..db.vault_keys import delete_all_vault_keys
from ..db.vault_pin import (
    create_pin_config,
    delete_pin_config,
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


class VaultDisabledError(Exception):
    """PORTAL_VAULT_KEK absent : la feature vault est désactivée (dev mode)."""


def vault_enabled() -> bool:
    return bool(get_settings().portal_vault_kek)


def _kek() -> bytes:
    kek_hex = get_settings().portal_vault_kek
    if not kek_hex:
        # Fail closed : dériver des clés depuis une KEK vide chiffrerait le
        # vault avec du vide. Ne doit jamais être silencieux.
        raise VaultDisabledError("PORTAL_VAULT_KEK is not set — vault disabled")
    return bytes.fromhex(kek_hex)


async def setup_pin(
    login: str, pin: str, session_id: str, conn: AsyncConnection
) -> PinSetupResult:
    await ensure_user_db(login, conn)  # FK guard : users.login doit exister
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


async def reset_vault(login: str, session_id: str, conn: AsyncConnection) -> None:
    vault_session.clear_session(session_id)
    await delete_all_vault_keys(login, conn)
    await delete_pin_config(login, conn)
    _log.info("vault_reset", login=login)


async def _dev_auto_unlock(login: str, session_id: str, conn: AsyncConnection) -> bool:
    """Mode dev (VAULT_DEV_PIN + dev_mode) : initialise/déverrouille sans friction.

    - Aucun PIN configuré → en crée un avec VAULT_DEV_PIN (comme un premier setup).
    - PIN configuré et VAULT_DEV_PIN le déverrouille → déverrouillé.
    - PIN configuré mais différent (l'utilisateur a choisi le sien) → False,
      SANS consommer de tentative ni risquer un lockout : retombe sur le flux
      normal, l'utilisateur saisit son vrai PIN à la main.
    """
    settings = get_settings()
    if not settings.dev_mode or not settings.vault_dev_pin:
        return False
    dev_pin = settings.vault_dev_pin

    if vault_session.is_unlocked(session_id):
        return True

    if not await has_pin_config(login, conn):
        await setup_pin(login, dev_pin, session_id, conn)
        return True

    config = await get_pin_config(login, conn)
    if config is None:
        return False
    try:
        wrap_key = derive_wrap_key(dev_pin, bytes(config["pin_salt"]), _kek())
        master_key = decrypt_master_key(bytes(config["encrypted_master_key"]), wrap_key)
    except InvalidKey:
        return False
    vault_session.set_master_key(session_id, master_key)
    _log.info("vault_dev_pin_auto_unlocked", login=login)
    return True


async def get_vault_status(
    login: str, session_id: str, conn: AsyncConnection
) -> Literal["disabled", "setup_required", "locked", "unlocked"]:
    if not vault_enabled():
        return "disabled"
    if await _dev_auto_unlock(login, session_id, conn):
        return "unlocked"
    if not await has_pin_config(login, conn):
        return "setup_required"
    if vault_session.is_unlocked(session_id):
        return "unlocked"
    return "locked"
