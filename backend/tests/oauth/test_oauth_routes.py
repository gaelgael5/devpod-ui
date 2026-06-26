# backend/tests/oauth/test_oauth_routes.py
"""Handlers OAuth (découverte + DCR) appelés directement, dépendances mockées."""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from portal.routes import oauth as r


def _cfg() -> Mock:
    c = Mock()
    c.server.external_url = "https://dev.yoops.org"
    return c


@pytest.mark.asyncio
async def test_protected_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r, "load_global", _cfg)
    res = await r.protected_resource()
    assert res["resource"] == "https://dev.yoops.org/mcp"
    assert res["authorization_servers"] == ["https://dev.yoops.org"]


@pytest.mark.asyncio
async def test_authorization_server_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r, "load_global", _cfg)
    res = await r.authorization_server_metadata()
    assert res["issuer"] == "https://dev.yoops.org"
    assert res["token_endpoint"] == "https://dev.yoops.org/oauth/token"
    assert res["registration_endpoint"] == "https://dev.yoops.org/oauth/register"
    assert res["code_challenge_methods_supported"] == ["S256"]
    assert res["token_endpoint_auth_methods_supported"] == ["none"]


@pytest.mark.asyncio
async def test_register_returns_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        r.service, "register_client", AsyncMock(return_value={"client_id": "mcpc_x"})
    )
    res = await r.register({"redirect_uris": ["https://claude.ai/cb"]}, conn=None)
    assert res["client_id"] == "mcpc_x"


@pytest.mark.asyncio
async def test_mcp_trailing_slash_redirects() -> None:
    req = Mock()
    req.url.query = ""
    res = await r.mcp_trailing_slash(req)
    assert res.status_code == 307
    assert res.headers["location"] == "/mcp/"
