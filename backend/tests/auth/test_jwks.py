from __future__ import annotations

import httpx
import pytest
import respx

from tests.auth.conftest import ISSUER, make_jwks_response

JWKS_URI = f"{ISSUER}/protocol/openid-connect/certs"


@pytest.mark.asyncio
async def test_jwks_cache_fetches_on_first_call() -> None:
    from portal.auth.jwks import JWKSCache

    with respx.mock:
        respx.get(JWKS_URI).mock(return_value=httpx.Response(200, json=make_jwks_response()))
        cache = JWKSCache(JWKS_URI)
        keyset = await cache.get_keyset()
        assert keyset is not None
        assert len(respx.calls) == 1


@pytest.mark.asyncio
async def test_jwks_cache_does_not_refetch_within_ttl() -> None:
    from portal.auth.jwks import JWKSCache

    with respx.mock:
        respx.get(JWKS_URI).mock(return_value=httpx.Response(200, json=make_jwks_response()))
        cache = JWKSCache(JWKS_URI, ttl=3600)
        await cache.get_keyset()
        await cache.get_keyset()
        assert len(respx.calls) == 1


@pytest.mark.asyncio
async def test_jwks_cache_refetches_when_forced() -> None:
    from portal.auth.jwks import JWKSCache

    with respx.mock:
        respx.get(JWKS_URI).mock(return_value=httpx.Response(200, json=make_jwks_response()))
        cache = JWKSCache(JWKS_URI, ttl=3600)
        await cache.get_keyset()
        await cache.get_keyset(refetch=True)
        assert len(respx.calls) == 2


@pytest.mark.asyncio
async def test_jwks_cache_raises_on_http_error() -> None:
    from portal.auth.jwks import JWKSCache

    with respx.mock:
        respx.get(JWKS_URI).mock(return_value=httpx.Response(503))
        cache = JWKSCache(JWKS_URI)
        with pytest.raises(httpx.HTTPStatusError):
            await cache.get_keyset()
