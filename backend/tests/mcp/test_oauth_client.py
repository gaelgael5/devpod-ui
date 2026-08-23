"""Cœur client OAuth 2.1 de la gateway vers un backend amont (Tranche 1)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from portal.mcp import oauth_client as oc
from portal.mcp.oauth_client import (
    ASMetadata,
    DiscoveryError,
    RegistrationError,
    TokenExchangeError,
    build_authorization_url,
    discover_metadata,
    exchange_code,
    refresh_token,
    register_client,
)
from portal.oauth.pkce import generate_pkce, verify_s256

_AS = {
    "issuer": "https://as.example.com",
    "authorization_endpoint": "https://as.example.com/authorize",
    "token_endpoint": "https://as.example.com/token",
    "registration_endpoint": "https://as.example.com/register",
    "scopes_supported": ["read", "write"],
}


def _patch(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real = httpx.AsyncClient

    def factory(*_a, **_kw):
        return real(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(oc.httpx, "AsyncClient", factory)


def _meta() -> ASMetadata:
    return ASMetadata.model_validate(_AS)


# ── PKCE ─────────────────────────────────────────────────────────────────────


def test_generate_pkce_roundtrip() -> None:
    v1, c1 = generate_pkce()
    assert verify_s256(v1, c1)
    v2, _ = generate_pkce()
    assert v1 != v2  # entropie par appel
    assert not verify_s256("mauvais", c1)


# ── Découverte ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discover_with_auth_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=_AS)
        return httpx.Response(404)

    _patch(monkeypatch, handler)
    meta = await discover_metadata("https://mcp.example.com/mcp", auth_url="https://as.example.com")
    assert meta.token_endpoint == "https://as.example.com/token"
    assert meta.registration_endpoint == "https://as.example.com/register"


@pytest.mark.asyncio
async def test_discover_via_protected_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        if req.url.path == "/.well-known/oauth-protected-resource":
            # Doit être interrogé sur l'ORIGINE du MCP, pas le chemin /mcp.
            assert req.url.host == "mcp.example.com"
            return httpx.Response(200, json={"authorization_servers": ["https://as.example.com"]})
        if req.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=_AS)
        return httpx.Response(404)

    _patch(monkeypatch, handler)
    meta = await discover_metadata("https://mcp.example.com/mcp")
    assert meta.authorization_endpoint == "https://as.example.com/authorize"
    assert "/.well-known/oauth-protected-resource" in seen


@pytest.mark.asyncio
async def test_discover_fallback_openid(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json=_AS)
        return httpx.Response(404)  # oauth-authorization-server absent

    _patch(monkeypatch, handler)
    meta = await discover_metadata("https://mcp.example.com", auth_url="https://as.example.com")
    assert meta.issuer == "https://as.example.com"


@pytest.mark.asyncio
async def test_discover_no_auth_server_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/.well-known/oauth-protected-resource":
            return httpx.Response(200, json={"authorization_servers": []})
        return httpx.Response(404)

    _patch(monkeypatch, handler)
    with pytest.raises(DiscoveryError):
        await discover_metadata("https://mcp.example.com/mcp")


# ── DCR ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_client_dcr(monkeypatch: pytest.MonkeyPatch) -> None:
    body: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        body.update(json.loads(req.content))
        return httpx.Response(201, json={"client_id": "cid-123", "client_secret": None})

    _patch(monkeypatch, handler)
    cid, secret = await register_client(
        _meta(), "https://portal.example/cb", client_name="devpod", scopes="read write"
    )
    assert cid == "cid-123"
    assert secret is None
    # Client public PKCE : pas d'auth secret, refresh demandé.
    assert body["token_endpoint_auth_method"] == "none"
    assert "refresh_token" in body["grant_types"]
    assert body["redirect_uris"] == ["https://portal.example/cb"]


@pytest.mark.asyncio
async def test_register_client_no_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    meta = _meta().model_copy(update={"registration_endpoint": None})
    with pytest.raises(RegistrationError):
        await register_client(meta, "https://portal.example/cb", client_name="x", scopes="")


# ── URL d'autorisation ───────────────────────────────────────────────────────


def test_build_authorization_url() -> None:
    url = build_authorization_url(
        _meta(),
        client_id="cid",
        redirect_uri="https://portal.example/cb",
        scopes="read write",
        state="st4te",
        code_challenge="chal",
        resource="https://mcp.example.com/mcp",
    )
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    assert parts.path == "/authorize"
    assert q["response_type"] == ["code"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["code_challenge"] == ["chal"]
    assert q["state"] == ["st4te"]
    assert q["resource"] == ["https://mcp.example.com/mcp"]


def test_build_authorization_url_appends_to_existing_query() -> None:
    meta = _meta().model_copy(
        update={"authorization_endpoint": "https://as.example.com/authorize?ui=1"}
    )
    url = build_authorization_url(
        meta,
        client_id="cid",
        redirect_uri="https://portal.example/cb",
        scopes="read",
        state="s",
        code_challenge="c",
    )
    assert "?ui=1&" in url
    assert parse_qs(urlsplit(url).query)["ui"] == ["1"]


# ── Échange / refresh ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exchange_code(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        sent.update({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
        return httpx.Response(
            200,
            json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "read"},
        )

    _patch(monkeypatch, handler)
    tok = await exchange_code(
        _meta(),
        client_id="cid",
        client_secret=None,
        code="the-code",
        code_verifier="ver",
        redirect_uri="https://portal.example/cb",
        resource="https://mcp.example.com/mcp",
    )
    assert tok.access_token == "at"
    assert tok.refresh_token == "rt"
    assert tok.expires_in == 3600
    assert sent["grant_type"] == "authorization_code"
    assert sent["code_verifier"] == "ver"
    assert sent["resource"] == "https://mcp.example.com/mcp"


@pytest.mark.asyncio
async def test_exchange_code_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    _patch(monkeypatch, handler)
    with pytest.raises(TokenExchangeError):
        await exchange_code(
            _meta(),
            client_id="cid",
            client_secret=None,
            code="bad",
            code_verifier="ver",
            redirect_uri="https://portal.example/cb",
        )


@pytest.mark.asyncio
async def test_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        sent.update({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
        return httpx.Response(200, json={"access_token": "at2", "expires_in": 1800})

    _patch(monkeypatch, handler)
    tok = await refresh_token(_meta(), client_id="cid", client_secret=None, refresh_token="old-rt")
    assert tok.access_token == "at2"
    assert sent["grant_type"] == "refresh_token"
    assert sent["refresh_token"] == "old-rt"
