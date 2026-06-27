from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import user_pin_config


async def create_pin_config(
    login: str,
    encrypted_master_key: bytes,
    pin_salt: bytes,
    encrypted_master_key_recovery: bytes,
    recovery_salt: bytes,
    conn: AsyncConnection,
) -> None:
    await conn.execute(
        insert(user_pin_config).values(
            login=login,
            encrypted_master_key=encrypted_master_key,
            pin_salt=pin_salt,
            encrypted_master_key_recovery=encrypted_master_key_recovery,
            recovery_salt=recovery_salt,
        )
    )


async def get_pin_config(login: str, conn: AsyncConnection) -> dict[str, Any] | None:
    row = (
        await conn.execute(
            select(user_pin_config).where(user_pin_config.c.login == login)
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def has_pin_config(login: str, conn: AsyncConnection) -> bool:
    return await get_pin_config(login, conn) is not None


async def update_pin_config(
    login: str,
    encrypted_master_key: bytes,
    pin_salt: bytes,
    encrypted_master_key_recovery: bytes,
    recovery_salt: bytes,
    conn: AsyncConnection,
) -> None:
    await conn.execute(
        update(user_pin_config)
        .where(user_pin_config.c.login == login)
        .values(
            encrypted_master_key=encrypted_master_key,
            pin_salt=pin_salt,
            encrypted_master_key_recovery=encrypted_master_key_recovery,
            recovery_salt=recovery_salt,
            pin_attempts=0,
            locked_until=None,
            updated_at=func.now(),
        )
    )


async def increment_pin_attempts(login: str, conn: AsyncConnection) -> int:
    result = await conn.execute(
        update(user_pin_config)
        .where(user_pin_config.c.login == login)
        .values(
            pin_attempts=user_pin_config.c.pin_attempts + 1,
            updated_at=func.now(),
        )
        .returning(user_pin_config.c.pin_attempts)
    )
    return int(result.scalar_one())


async def reset_pin_attempts(login: str, conn: AsyncConnection) -> None:
    await conn.execute(
        update(user_pin_config)
        .where(user_pin_config.c.login == login)
        .values(pin_attempts=0, locked_until=None, updated_at=func.now())
    )


async def lock_pin(login: str, locked_until: datetime, conn: AsyncConnection) -> None:
    await conn.execute(
        update(user_pin_config)
        .where(user_pin_config.c.login == login)
        .values(locked_until=locked_until, updated_at=func.now())
    )


async def delete_pin_config(login: str, conn: AsyncConnection) -> None:
    await conn.execute(
        delete(user_pin_config).where(user_pin_config.c.login == login)
    )
