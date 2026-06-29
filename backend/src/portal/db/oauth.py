"""Accès DB de l'Authorization Server OAuth de la passerelle MCP."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import mcp_apikey, mcp_oauth_authcode, mcp_oauth_client


async def insert_client(
    conn: AsyncConnection,
    *,
    client_id: str,
    redirect_uris: list[str],
    client_name: str,
    metadata: dict[str, Any],
) -> None:
    await conn.execute(
        insert(mcp_oauth_client).values(
            client_id=client_id,
            redirect_uris=redirect_uris,
            client_name=client_name,
            client_metadata=metadata,
        )
    )


async def get_client(conn: AsyncConnection, client_id: str) -> dict[str, Any] | None:
    row = (
        await conn.execute(
            select(mcp_oauth_client).where(mcp_oauth_client.c.client_id == client_id)
        )
    ).mappings().first()
    return dict(row) if row else None


async def insert_authcode(
    conn: AsyncConnection,
    *,
    code_hash: str,
    client_id: str,
    owner_login: str,
    redirect_uri: str,
    code_challenge: str,
    scope: str,
    grants: list[dict[str, Any]],
    profile_id: str | None,
    expires_at: datetime,
) -> None:
    await conn.execute(
        insert(mcp_oauth_authcode).values(
            code_hash=code_hash,
            client_id=client_id,
            owner_login=owner_login,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            grants=grants,
            profile_id=profile_id,
            expires_at=expires_at,
        )
    )


async def consume_authcode(conn: AsyncConnection, code_hash: str) -> dict[str, Any] | None:
    """Marque le code utilisé et le retourne, de façon atomique.

    None si le code est absent, déjà utilisé ou expiré (deny-by-default).
    """
    stmt = (
        update(mcp_oauth_authcode)
        .where(
            mcp_oauth_authcode.c.code_hash == code_hash,
            mcp_oauth_authcode.c.used.is_(False),
            mcp_oauth_authcode.c.expires_at > func.now(),
        )
        .values(used=True)
        .returning(*mcp_oauth_authcode.c)
    )
    row = (await conn.execute(stmt)).mappings().first()
    return dict(row) if row else None


async def find_apikey_by_refresh_hash(
    conn: AsyncConnection, refresh_hash: str
) -> dict[str, Any] | None:
    row = (
        await conn.execute(
            select(mcp_apikey).where(
                mcp_apikey.c.refresh_token_hash == refresh_hash,
                mcp_apikey.c.revoked.is_(False),
            )
        )
    ).mappings().first()
    return dict(row) if row else None


async def insert_oauth_token(
    conn: AsyncConnection,
    *,
    id: str,
    owner_login: str,
    token_hash: str,
    client_id: str,
    refresh_token_hash: str,
    expires_at: datetime | None,
    profile_id: str | None,
) -> None:
    """Insère un access token OAuth = une apikey kind='oauth'."""
    await conn.execute(
        insert(mcp_apikey).values(
            id=id,
            owner_login=owner_login,
            token_hash=token_hash,
            label="oauth",
            kind="oauth",
            client_id=client_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            profile_id=profile_id,
        )
    )


async def rotate_token(
    conn: AsyncConnection, *, apikey_id: str, token_hash: str, refresh_token_hash: str
) -> None:
    """Rotation refresh : remplace access + refresh sur la même apikey (grants conservés)."""
    await conn.execute(
        update(mcp_apikey)
        .where(mcp_apikey.c.id == apikey_id)
        .values(token_hash=token_hash, refresh_token_hash=refresh_token_hash)
    )
