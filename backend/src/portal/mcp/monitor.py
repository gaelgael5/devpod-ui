from __future__ import annotations

import asyncio
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.engine import _get_engine
from portal.db.mcp import get_backend_key_secret, list_all_enabled_backends, list_backend_keys
from portal.mcp.catalog import sync_backend
from portal.mcp.connections import BackendUnavailable, open_session
from portal.mcp.runtime_secrets import UnresolvableSecret, resolve_grant_key

_log = structlog.get_logger(__name__)

_PROBE_TIMEOUT_S = 60.0  # timeout global par probe (connexion + sync)


class BackendHealth(BaseModel):
    """Statut de santé d'un backend MCP, dérivé du dernier monitoring."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["up", "down", "unknown"]
    error: str | None = None


# Registre santé en mémoire. Écrit par la boucle de fond, lu par les handlers.
# Sûr sous un event loop mono-thread : set_health/get_health n'ont aucun await
# entre lecture et écriture (pas de torn read ni lost update). NE PAS introduire
# d'await dans set_health/get_health sans repenser la synchro.
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
    """Synchronise le catalogue d'un backend et en déduit sa santé (up/down).

    Les backends `internal` (DevPod, etc.) sont hébergés dans le portail lui-même :
    aucune connexion réseau n'est nécessaire, ils sont toujours up.
    """
    if backend_row.get("transport") == "internal":
        health = BackendHealth(status="up")
        set_health(backend_row["id"], health)
        return health

    session_fn = open_session_fn if open_session_fn is not None else open_session
    backend_id = backend_row["id"]
    transport = backend_row.get("transport", "streamable_http")
    url = backend_row["url"]
    _log.info(
        "mcp_monitor_probe_start",
        backend_id=backend_id,
        url=url,
        transport=transport,
    )
    bearer = await _resolve_monitor_bearer(conn, backend_id)
    # Seul BackendUnavailable (injoignable) => down. Une autre erreur (ex. DB pendant
    # le sync) n'est pas imputable au backend : elle remonte à run_monitor_pass (loggée),
    # la santé conserve sa dernière valeur connue plutôt que d'afficher un faux "down".
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_S):
            async with session_fn(url, transport=transport, bearer=bearer) as session:
                await sync_backend(conn, backend_id=backend_id, session=session)
        health = BackendHealth(status="up")
    except TimeoutError:
        _log.warning(
            "mcp_monitor_probe_timeout",
            backend_id=backend_id,
            url=url,
            transport=transport,
            timeout_s=_PROBE_TIMEOUT_S,
        )
        health = BackendHealth(status="down", error=f"probe timeout après {_PROBE_TIMEOUT_S}s")
    except BackendUnavailable as exc:
        health = BackendHealth(status="down", error=str(exc))
    set_health(backend_id, health)
    _log.info(
        "mcp_monitor_probe_done",
        backend_id=backend_id,
        url=url,
        transport=transport,
        status=health.status,
        error=health.error,
    )
    return health


async def run_monitor_pass(*, open_session_fn: Any | None = None) -> None:
    """Une passe de monitoring sur tous les backends enabled (chacun en transaction isolée)."""
    async with _get_engine().connect() as conn:
        backends = await list_all_enabled_backends(conn)
    for backend in backends:
        try:
            async with _get_engine().begin() as conn:
                await monitor_backend_once(conn, backend, open_session_fn=open_session_fn)
        except Exception as exc:  # noqa: BLE001 — une erreur backend n'interrompt pas la passe
            _log.warning("mcp_monitor_backend_failed", backend_id=backend["id"], error=str(exc))


async def monitor_loop(interval_s: float, *, open_session_fn: Any | None = None) -> None:
    """Boucle de fond : monitore tous les backends toutes les interval_s secondes."""
    while True:
        try:
            await run_monitor_pass(open_session_fn=open_session_fn)
        except Exception as exc:  # noqa: BLE001 — une boucle de fond ne doit jamais mourir
            _log.exception("mcp_monitor_pass_failed", error=str(exc))
        await asyncio.sleep(interval_s)
