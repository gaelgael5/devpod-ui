"""Persistance des clés SSH workspace en base de données."""
from __future__ import annotations

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import workspace_ssh_keys


async def upsert_ssh_key_db(
    login: str,
    workspace_name: str,
    private_key_path: str,
    public_key: str,
    conn: AsyncConnection,
) -> None:
    existing = (
        await conn.execute(
            select(workspace_ssh_keys.c.id).where(
                (workspace_ssh_keys.c.login == login)
                & (workspace_ssh_keys.c.workspace_name == workspace_name)
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        await conn.execute(
            insert(workspace_ssh_keys).values(
                login=login,
                workspace_name=workspace_name,
                private_key_path=private_key_path,
                public_key=public_key,
            )
        )
    else:
        await conn.execute(
            update(workspace_ssh_keys)
            .where(
                (workspace_ssh_keys.c.login == login)
                & (workspace_ssh_keys.c.workspace_name == workspace_name)
            )
            .values(private_key_path=private_key_path, public_key=public_key)
        )


async def get_ssh_key_db(
    login: str, workspace_name: str, conn: AsyncConnection
) -> str | None:
    """Retourne la clé publique ou None si absente."""
    row = (
        await conn.execute(
            select(workspace_ssh_keys.c.public_key).where(
                (workspace_ssh_keys.c.login == login)
                & (workspace_ssh_keys.c.workspace_name == workspace_name)
            )
        )
    ).scalar_one_or_none()
    return row


async def delete_ssh_key_db(
    login: str, workspace_name: str, conn: AsyncConnection
) -> None:
    await conn.execute(
        delete(workspace_ssh_keys).where(
            (workspace_ssh_keys.c.login == login)
            & (workspace_ssh_keys.c.workspace_name == workspace_name)
        )
    )
