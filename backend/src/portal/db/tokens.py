"""Persistance des tokens de jointure de nœuds (node_join_tokens)."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import node_join_tokens

_TOKEN_TTL_SECONDS = 3600  # §E-27 : TTL court, 1h


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_token(
    node_name: str,
    address: str,
    conn: AsyncConnection,
) -> str:
    """Génère un token aléatoire, le stocke hashé avec TTL. Retourne le token en clair. §E-27."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(seconds=_TOKEN_TTL_SECONDS)
    await conn.execute(
        node_join_tokens.insert().values(
            token_hash=_token_hash(token),
            node_name=node_name,
            address=address,
            expires_at=expires_at,
            used=False,
        )
    )
    return token


async def consume_token(token: str, conn: AsyncConnection) -> tuple[str, str]:
    """Valide et consomme un join token. Retourne (node_name, address). §E-27.

    SELECT FOR UPDATE garantit l'usage unique même sous concurrence.
    """
    token_hash = _token_hash(token)
    row = (
        await conn.execute(
            select(node_join_tokens)
            .where(node_join_tokens.c.token_hash == token_hash)
            .with_for_update()
        )
    ).mappings().one_or_none()

    if row is None:
        raise ValueError("Token not found or already used")
    if row["used"]:
        raise ValueError("Token already used")
    if datetime.now(UTC) > row["expires_at"]:
        raise ValueError("Token expired")

    await conn.execute(
        update(node_join_tokens)
        .where(node_join_tokens.c.token_hash == token_hash)
        .values(used=True, used_at=datetime.now(UTC))
    )
    return str(row["node_name"]), str(row["address"])
