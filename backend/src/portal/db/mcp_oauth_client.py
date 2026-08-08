"""CRUD des tables du client OAuth de la gateway (Tranche 2).

Trois tables (cf. migration 084) : le client enregistré par backend
(`mcp_backend_oauth_client`), le token par (backend, utilisateur)
(`mcp_backend_oauth_token`), la requête d'autorisation en vol
(`mcp_backend_oauth_pending`). Les secrets (client_secret, access/refresh) sont
déjà chiffrés par l'appelant — ce module ne manipule que des blobs opaques.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import (
    mcp_backend_oauth_client,
    mcp_backend_oauth_pending,
    mcp_backend_oauth_token,
)

# ── Client enregistré (DCR) + métadonnées AS, un par backend ─────────────────


async def upsert_oauth_client(
    conn: AsyncConnection,
    backend_id: str,
    *,
    issuer: str,
    authorization_endpoint: str,
    token_endpoint: str,
    registration_endpoint: str | None,
    client_id: str,
    client_secret_enc: bytes | None,
    scopes: str,
) -> None:
    values = {
        "backend_id": backend_id,
        "issuer": issuer,
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "registration_endpoint": registration_endpoint,
        "client_id": client_id,
        "client_secret_enc": client_secret_enc,
        "scopes": scopes,
    }
    await conn.execute(
        pg_insert(mcp_backend_oauth_client)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["backend_id"],
            set_={k: v for k, v in values.items() if k != "backend_id"}
            | {"updated_at": func.now()},
        )
    )


async def get_oauth_client(conn: AsyncConnection, backend_id: str) -> dict[str, Any] | None:
    row = (
        (
            await conn.execute(
                select(mcp_backend_oauth_client).where(
                    mcp_backend_oauth_client.c.backend_id == backend_id
                )
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


# ── Token par (backend, utilisateur) ─────────────────────────────────────────


async def upsert_oauth_token(
    conn: AsyncConnection,
    backend_id: str,
    user_login: str,
    *,
    access_token_enc: bytes,
    refresh_token_enc: bytes | None,
    expires_at: datetime | None,
    scopes: str,
) -> None:
    values = {
        "backend_id": backend_id,
        "user_login": user_login,
        "access_token_enc": access_token_enc,
        "refresh_token_enc": refresh_token_enc,
        "expires_at": expires_at,
        "scopes": scopes,
    }
    await conn.execute(
        pg_insert(mcp_backend_oauth_token)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["backend_id", "user_login"],
            set_={k: v for k, v in values.items() if k not in ("backend_id", "user_login")}
            | {"updated_at": func.now()},
        )
    )


async def get_oauth_token(
    conn: AsyncConnection, backend_id: str, user_login: str
) -> dict[str, Any] | None:
    row = (
        (
            await conn.execute(
                select(mcp_backend_oauth_token).where(
                    mcp_backend_oauth_token.c.backend_id == backend_id,
                    mcp_backend_oauth_token.c.user_login == user_login,
                )
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def delete_oauth_token(conn: AsyncConnection, backend_id: str, user_login: str) -> bool:
    res = await conn.execute(
        delete(mcp_backend_oauth_token)
        .where(
            mcp_backend_oauth_token.c.backend_id == backend_id,
            mcp_backend_oauth_token.c.user_login == user_login,
        )
        .returning(mcp_backend_oauth_token.c.backend_id)
    )
    return res.first() is not None


# ── Requête d'autorisation en vol (state + verifier PKCE) ────────────────────


async def insert_pending(
    conn: AsyncConnection,
    *,
    state: str,
    backend_id: str,
    user_login: str,
    code_verifier: str,
    redirect_uri: str,
    expires_at: datetime,
) -> None:
    await conn.execute(
        pg_insert(mcp_backend_oauth_pending).values(
            state=state,
            backend_id=backend_id,
            user_login=user_login,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            expires_at=expires_at,
        )
    )


async def consume_pending(conn: AsyncConnection, state: str) -> dict[str, Any] | None:
    """Récupère ET supprime (usage unique) la requête en vol. None si absente/expirée.

    La suppression inconditionnelle du state consommé évite tout rejeu, même si la
    ligne était expirée.
    """
    row = (
        (
            await conn.execute(
                delete(mcp_backend_oauth_pending)
                .where(mcp_backend_oauth_pending.c.state == state)
                .returning(*mcp_backend_oauth_pending.c)
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    data = dict(row)
    if data["expires_at"] < datetime.now(UTC):
        return None
    return data
