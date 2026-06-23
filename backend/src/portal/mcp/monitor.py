from __future__ import annotations

from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.mcp import get_backend_key_secret, list_backend_keys
from portal.mcp.catalog import sync_backend
from portal.mcp.connections import BackendUnavailable, open_session
from portal.mcp.runtime_secrets import UnresolvableSecret, resolve_grant_key

_log = structlog.get_logger(__name__)


class BackendHealth(BaseModel):
    """Statut de santé d'un backend MCP, dérivé du dernier monitoring."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["up", "down", "unknown"]
    error: str | None = None


_HEALTH: dict[str, BackendHealth] = {}


def set_health(backend_id: str, health: BackendHealth) -> None:
    _HEALTH[backend_id] = health


def get_health(backend_id: str) -> BackendHealth:
    return _HEALTH.get(backend_id, BackendHealth(status="unknown"))


def health_snapshot() -> dict[str, BackendHealth]:
    return dict(_HEALTH)


def reset_health() -> None:
    _HEALTH.clear()


async def _resolve_monitor_bearer(conn: AsyncConnection, backend_id: str) -> str | None:
    """Première clé enabled dont le secret se résout au runtime, sinon None (best-effort)."""
    for key in await list_backend_keys(conn, backend_id):
        if not key["enabled"]:
            continue
        key_row = await get_backend_key_secret(conn, backend_id, key["id"])
        try:
            secret = await resolve_grant_key(key_row)
        except UnresolvableSecret:
            continue
        if secret is not None:
            return secret.reveal()
    return None


async def monitor_backend_once(
    conn: AsyncConnection,
    backend_row: dict[str, Any],
    *,
    open_session_fn: Any | None = None,
) -> BackendHealth:
    """Synchronise le catalogue d'un backend et en déduit sa santé (up/down)."""
    session_fn = open_session_fn if open_session_fn is not None else open_session
    bearer = await _resolve_monitor_bearer(conn, backend_row["id"])
    try:
        async with session_fn(backend_row["url"], bearer=bearer) as session:
            await sync_backend(conn, backend_id=backend_row["id"], session=session)
        health = BackendHealth(status="up")
    except BackendUnavailable as exc:
        health = BackendHealth(status="down", error=str(exc))
    set_health(backend_row["id"], health)
    return health
