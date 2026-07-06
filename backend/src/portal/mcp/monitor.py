from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from portal.db.engine import _get_engine
from portal.db.mcp import get_backend_key_secret, list_all_enabled_backends, list_backend_keys
from portal.mcp.catalog import fetch_backend_catalog, write_backend_catalog
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


@asynccontextmanager
async def _conn_or_begin(conn: AsyncConnection | None) -> AsyncIterator[AsyncConnection]:
    """Réutilise `conn` s'il est fourni, sinon ouvre une transaction courte dédiée.

    Permet à monitor_backend_once(None, ...) (run_monitor_pass) d'acquérir des
    connexions au fil de l'eau — jamais pendant l'I/O réseau — tout en laissant
    les appelants qui fournissent déjà une connexion (route /probe, tests) la
    réutiliser telle quelle, sans changement de comportement (bug 026).
    """
    if conn is not None:
        yield conn
        return
    async with _get_engine().begin() as new_conn:
        yield new_conn


async def monitor_backend_once(
    conn: AsyncConnection | None,
    backend_row: dict[str, Any],
    *,
    open_session_fn: Any | None = None,
    trigger: str = "monitor",
) -> BackendHealth:
    """Synchronise le catalogue d'un backend et en déduit sa santé (up/down).

    Les backends `internal` (DevPod, etc.) sont hébergés dans le portail lui-même :
    aucune connexion réseau n'est nécessaire, ils sont toujours up. Leur catalogue
    n'est resynchronisé qu'à la création d'un user ou au redémarrage du portail —
    ce passage de moniteur (périodique ou déclenché à la main via /probe) est
    l'occasion de le rafraîchir aussi, ex. après un changement de logs.enabled.

    `conn` est optionnel : si fourni (route /probe, tests), il est réutilisé pour
    toute la durée de l'appel. Si `None` (run_monitor_pass), les connexions sont
    acquises à la demande — jamais tenues pendant l'I/O réseau du probe (bug 026).
    """
    if backend_row.get("transport") == "internal":
        from .devpod_bootstrap import ensure_devpod_backend

        async with _conn_or_begin(conn) as c:
            await ensure_devpod_backend(c, backend_row["owner_login"])
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
    if conn is not None:
        bearer = await _resolve_monitor_bearer(conn, backend_id)
    else:
        async with _get_engine().connect() as read_conn:
            bearer = await _resolve_monitor_bearer(read_conn, backend_id)
    # Seul BackendUnavailable (injoignable) => down. Une autre erreur (ex. DB pendant
    # le sync) n'est pas imputable au backend : elle remonte à run_monitor_pass (loggée),
    # la santé conserve sa dernière valeur connue plutôt que d'afficher un faux "down".
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_S):
            async with session_fn(url, transport=transport, bearer=bearer) as session:
                # I/O réseau seule ici — aucune connexion DB tenue ouverte (bug 026).
                primitives, kinds = await fetch_backend_catalog(session)
        async with _conn_or_begin(conn) as c:
            await write_backend_catalog(
                c,
                backend_id=backend_id,
                primitives=primitives,
                kinds=kinds,
                protect_quarantine=not bool(backend_row.get("quarantine_disabled", False)),
                trigger=trigger,
            )
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


class KeyProbeResult(BaseModel):
    """Verdict du test d'une clé de service (handshake authentifié avec CETTE clé)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok", "failed"]
    error: str | None = None


async def probe_backend_key(
    conn: AsyncConnection,
    backend_row: dict[str, Any],
    key_id: str,
    *,
    open_session_fn: Any | None = None,
) -> KeyProbeResult:
    """Teste une clé de service : handshake MCP authentifié avec cette clé précise.

    Contrairement au probe santé (_resolve_monitor_bearer prend la première clé
    résoluble), la clé est ici imposée — un secret irrésoluble ou une connexion
    refusée est un verdict sur la clé, pas sur le backend.

    Lève KeyError si la clé n'existe pas pour ce backend.
    """
    backend_id = backend_row["id"]
    key_row = await get_backend_key_secret(conn, backend_id, key_id)
    if key_row is None:
        raise KeyError(key_id)
    try:
        secret = await resolve_grant_key(key_row)
    except UnresolvableSecret as exc:
        return KeyProbeResult(status="failed", error=f"secret irrésoluble : {exc}")
    if secret is None:
        return KeyProbeResult(status="failed", error="secret introuvable")

    session_fn = open_session_fn if open_session_fn is not None else open_session
    url = backend_row["url"]
    transport = backend_row.get("transport", "streamable_http")
    _log.info("mcp_key_probe_start", backend_id=backend_id, key_id=key_id, url=url)
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_S):
            async with session_fn(url, transport=transport, bearer=secret.reveal()) as session:
                await fetch_backend_catalog(session)
        result = KeyProbeResult(status="ok")
    except TimeoutError:
        result = KeyProbeResult(status="failed", error=f"timeout après {_PROBE_TIMEOUT_S}s")
    except BackendUnavailable as exc:
        result = KeyProbeResult(status="failed", error=str(exc))
    _log.info(
        "mcp_key_probe_done",
        backend_id=backend_id,
        key_id=key_id,
        status=result.status,
        error=result.error,
    )
    return result


async def run_monitor_pass(*, open_session_fn: Any | None = None) -> None:
    """Une passe de monitoring sur tous les backends enabled.

    Connexions DB acquises au fil de l'eau par backend (bearer, puis écriture du
    catalogue) — jamais tenues pendant l'I/O réseau du probe (bug 026).
    """
    async with _get_engine().connect() as conn:
        backends = await list_all_enabled_backends(conn)
    for backend in backends:
        try:
            await monitor_backend_once(None, backend, open_session_fn=open_session_fn)
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
