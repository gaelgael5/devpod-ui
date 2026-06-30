from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from mcp import ClientSession
from mcp.client.sse import sse_client  # type: ignore[import-not-found]
from mcp.client.streamable_http import (  # type: ignore[import-not-found]
    create_mcp_http_client,
    streamable_http_client,
)

_log = structlog.get_logger(__name__)


class BackendUnavailable(Exception):
    """Le backend MCP est injoignable ou a échoué à l'initialisation."""

    def __init__(self, message: str, *, backend_id: str | None = None) -> None:
        super().__init__(message)
        self.backend_id = backend_id


@asynccontextmanager
async def open_session(
    url: str,
    *,
    transport: str = "streamable_http",
    bearer: str | None = None,
    timeout_s: float = 30.0,
    sse_read_timeout_s: float = 300.0,
) -> AsyncIterator[ClientSession]:
    """Ouvre une session MCP vers un backend selon son transport, initialisée.

    Supporte `streamable_http` (défaut) et `sse` (protocole legacy).
    Injecte un bearer token si fourni. Toute erreur de connexion ou
    d'initialisation est convertie en BackendUnavailable.
    """
    headers: dict[str, str] | None = {"Authorization": f"Bearer {bearer}"} if bearer else None
    _log.debug(
        "mcp_open_session_start", url=url, transport=transport, has_bearer=bearer is not None
    )
    try:
        if transport == "sse":
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
