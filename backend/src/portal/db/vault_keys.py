from __future__ import annotations

from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import user_harpocrate_keys


async def create_vault_key(
    login: str,
    identifier: str,
    encrypted_token: bytes,
    url: str,
    description: str,
    conn: AsyncConnection,
) -> None:
    await conn.execute(
        insert(user_harpocrate_keys).values(
            login=login,
            identifier=identifier,
            encrypted_token=encrypted_token,
            url=url,
            description=description,
        )
    )


async def list_vault_keys(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            select(
                user_harpocrate_keys.c.id,
                user_harpocrate_keys.c.identifier,
                user_harpocrate_keys.c.url,
                user_harpocrate_keys.c.description,
                user_harpocrate_keys.c.created_at,
            ).where(user_harpocrate_keys.c.login == login)
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def get_encrypted_token(
    login: str, identifier: str, conn: AsyncConnection
) -> bytes | None:
    row = (
        await conn.execute(
            select(user_harpocrate_keys.c.encrypted_token)
            .where(user_harpocrate_keys.c.login == login)
            .where(user_harpocrate_keys.c.identifier == identifier)
        )
    ).one_or_none()
    return bytes(row[0]) if row is not None else None


async def delete_vault_key(login: str, identifier: str, conn: AsyncConnection) -> bool:
    result = await conn.execute(
        delete(user_harpocrate_keys)
        .where(user_harpocrate_keys.c.login == login)
        .where(user_harpocrate_keys.c.identifier == identifier)
    )
    return result.rowcount > 0


async def vault_key_exists(login: str, identifier: str, conn: AsyncConnection) -> bool:
    return await get_encrypted_token(login, identifier, conn) is not None
