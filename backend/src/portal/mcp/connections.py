from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from mcp import ClientSession
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


@asynccontextmanager
async def open_session(
    url: str,
    *,
    bearer: str | None = None,
    timeout_s: float = 30.0,
    sse_read_timeout_s: float = 300.0,
) -> AsyncIterator[ClientSession]:
    """Ouvre une session MCP Streamable HTTP vers un backend, initialisée.

    Injecte un bearer token si fourni. Toute erreur de connexion ou
    d'initialisation est convertie en BackendUnavailable (le runtime exclut
    alors le backend sans faire échouer l'agrégation globale).

    Args:
        url: URL du backend MCP (ex. http://host/mcp).
        bearer: Token d'autorisation Bearer optionnel.
        timeout_s: Timeout de connexion et requête (défaut 30s).
        sse_read_timeout_s: Timeout de lecture du flux SSE, utilisé pour les
            réponses streamées des tools longs (défaut 300s). Correspond à
            l'ancien paramètre ``sse_read_timeout`` de l'API dépréciée.

    Note SDK (mcp 1.28+) : l'API actuelle de streamable_http_client accepte
    un httpx.AsyncClient pré-configuré ; headers et timeout sont passés via
    create_mcp_http_client.
    """
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else None
    timeout = httpx.Timeout(timeout_s, read=sse_read_timeout_s)
    http_client = create_mcp_http_client(headers=headers, timeout=timeout)
    try:
        async with (
            http_client,
            streamable_http_client(url, http_client=http_client) as (read, write, _get_sid),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session
    except BackendUnavailable:
        raise
    except Exception as exc:
        _log.warning(
            "mcp_backend_unavailable",
            url=url,
            error=type(exc).__name__,
            # bearer intentionnellement absent du log
        )
        raise BackendUnavailable(
            f"backend injoignable: {type(exc).__name__}",
        ) from exc
