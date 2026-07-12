from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import (  # type: ignore[attr-defined]
    create_mcp_http_client,
    streamable_http_client,
)

_log = structlog.get_logger(__name__)


class BackendUnavailable(Exception):
    """Le backend MCP est injoignable ou a échoué à l'initialisation."""

    def __init__(self, message: str, *, backend_id: str | None = None) -> None:
        super().__init__(message)
        self.backend_id = backend_id


def _sse_init_settle_s() -> float:
    """Délai de stabilisation post-initialize pour le transport SSE (settings)."""
    from portal.settings import get_settings

    return get_settings().mcp_sse_init_settle_s


@asynccontextmanager
async def open_session(
    url: str,
    *,
    transport: str = "streamable_http",
    bearer: str | None = None,
    timeout_s: float = 30.0,
    sse_read_timeout_s: float = 300.0,
    sse_init_settle_s: float | None = None,
) -> AsyncIterator[ClientSession]:
    """Ouvre une session MCP vers un backend selon son transport, initialisée.

    Supporte `streamable_http` (défaut) et `sse` (protocole legacy).
    Injecte un bearer token si fourni. Toute erreur de connexion ou
    d'initialisation est convertie en BackendUnavailable.

    Transport `sse` uniquement : après `initialize`, un court settle laisse le
    serveur démarrer sa boucle de dispatch avant le premier message applicatif.
    Sans lui, le premier appel (ex. list_tools du probe de catalogue) part avant
    que le serveur soit prêt, est perdu, et la session meurt — le probe timeout
    et le backend apparaît Offline alors que l'auth et l'URL sont correctes.
    Durée via settings (`mcp_sse_init_settle_s`), surchargée par le paramètre.
    """
    headers: dict[str, str] | None = {"Authorization": f"Bearer {bearer}"} if bearer else None
    _log.debug(
        "mcp_open_session_start", url=url, transport=transport, has_bearer=bearer is not None
    )
    try:
        if transport == "sse":
            settle = sse_init_settle_s if sse_init_settle_s is not None else _sse_init_settle_s()
            async with (
                sse_client(
                    url,
                    headers=headers,
                    timeout=timeout_s,
                    sse_read_timeout=sse_read_timeout_s,
                ) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                if settle > 0:
                    await asyncio.sleep(settle)
                _log.debug("mcp_open_session_ok", url=url, transport=transport)
                yield session
        else:
            timeout = httpx.Timeout(timeout_s, read=sse_read_timeout_s)
            http_client = create_mcp_http_client(headers=headers, timeout=timeout)
            async with (
                http_client,
                streamable_http_client(url, http_client=http_client) as (read, write, _get_sid),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                _log.debug("mcp_open_session_ok", url=url, transport=transport)
                yield session
    except BackendUnavailable:
        raise
    except Exception as exc:
        _log.warning(
            "mcp_backend_unavailable",
            url=url,
            transport=transport,
            exc_type=type(exc).__name__,
            error=str(exc),
            # bearer intentionnellement absent du log
        )
        raise BackendUnavailable(
            f"backend injoignable ({type(exc).__name__}): {exc}",
        ) from exc
