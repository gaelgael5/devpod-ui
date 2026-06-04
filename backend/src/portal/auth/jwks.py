from __future__ import annotations

import time

import httpx
import structlog
from joserfc.jwk import KeySet

_log = structlog.get_logger(__name__)


class JWKSCache:
    """Cache de JWKS avec TTL et possibilité de refetch forcé (pour kid inconnu)."""

    def __init__(self, jwks_uri: str, ttl: int = 3600) -> None:
        self._uri = jwks_uri
        self._ttl = ttl
        self._keyset: KeySet | None = None
        self._fetched_at: float = 0.0

    async def get_keyset(self, *, refetch: bool = False) -> KeySet:
        now = time.monotonic()
        stale = self._keyset is None or (now - self._fetched_at) > self._ttl
        if refetch or stale:
            await self._fetch()
        assert self._keyset is not None
        return self._keyset

    async def _fetch(self) -> None:
        _log.info("jwks_fetch", uri=self._uri)
        async with httpx.AsyncClient() as client:
            resp = await client.get(self._uri, timeout=10.0)
            resp.raise_for_status()
        self._keyset = KeySet.import_key_set(resp.json())
        self._fetched_at = time.monotonic()
        _log.info("jwks_fetched", key_count=len(self._keyset.keys))
