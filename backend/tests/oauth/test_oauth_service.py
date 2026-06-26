# backend/tests/oauth/test_oauth_service.py
"""Service OAuth — logique d'échange/refresh, accès DB mockés."""
from __future__ import annotations

import base64
import hashlib
from unittest.mock import AsyncMock

import pytest

from portal.oauth import service


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@pytest.mark.asyncio
async def test_exchange_code_success(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = "v" * 64
    row = {
        "client_id": "c1",
        "redirect_uri": "https://r/cb",
        "code_challenge": _challenge(verifier),
        "owner_login": "alice",
        "grants": [{"backend_id": "b1", "expose_mode": "all"}],
    }
    inserted: dict = {}
    grants_set: list = []

    async def fake_insert(conn, **kw):  # noqa: ANN001, ANN003
        inserted.update(kw)

    async def fake_set_grant(conn, **kw):  # noqa: ANN001, ANN003
        grants_set.append(kw)

    monkeypatch.setattr(service.db, "consume_authcode", AsyncMock(return_value=row))
    monkeypatch.setattr(service.db, "insert_oauth_token", fake_insert)
    monkeypatch.setattr(service.mcp_db, "set_grant", fake_set_grant)

    res = await service.exchange_code(
        conn=None, code="code", client_id="c1", redirect_uri="https://r/cb", code_verifier=verifier
    )
    assert res["access_token"].startswith("mcpk_")
    assert res["token_type"] == "Bearer"
    assert res["refresh_token"].startswith("mcpr_")
    assert inserted["client_id"] == "c1"
    assert inserted["token_hash"]  # access token haché transmis à la DB
    assert grants_set and grants_set[0]["backend_id"] == "b1"


@pytest.mark.asyncio
async def test_exchange_code_bad_pkce(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {
        "client_id": "c1",
        "redirect_uri": "https://r/cb",
        "code_challenge": _challenge("v" * 64),
        "owner_login": "alice",
        "grants": [],
    }
    monkeypatch.setattr(service.db, "consume_authcode", AsyncMock(return_value=row))
    with pytest.raises(service.OAuthError) as exc:
        await service.exchange_code(
            conn=None, code="c", client_id="c1", redirect_uri="https://r/cb", code_verifier="wrong"
        )
    assert exc.value.error == "invalid_grant"


@pytest.mark.asyncio
async def test_exchange_code_already_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service.db, "consume_authcode", AsyncMock(return_value=None))
    with pytest.raises(service.OAuthError):
        await service.exchange_code(
            conn=None, code="c", client_id="c1", redirect_uri="https://r/cb", code_verifier="v"
        )


@pytest.mark.asyncio
async def test_exchange_code_wrong_client(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {
        "client_id": "other",
        "redirect_uri": "https://r/cb",
        "code_challenge": "x",
        "owner_login": "alice",
        "grants": [],
    }
    monkeypatch.setattr(service.db, "consume_authcode", AsyncMock(return_value=row))
    with pytest.raises(service.OAuthError):
        await service.exchange_code(
            conn=None, code="c", client_id="c1", redirect_uri="https://r/cb", code_verifier="v"
        )


def test_ensure_valid_redirect_uri_accepts_https_and_loopback() -> None:
    service.ensure_valid_redirect_uri("https://claude.ai/api/mcp/auth_callback")
    service.ensure_valid_redirect_uri("http://localhost:1234/cb")
    service.ensure_valid_redirect_uri("http://127.0.0.1/cb")


def test_ensure_valid_redirect_uri_rejects_dangerous_schemes() -> None:
    for bad in (
        "javascript:alert(document.cookie)",
        "data:text/html,<script>1</script>",
        "http://evil.example.com/cb",  # http non loopback
        "https://ok.example.com/cb#frag",  # fragment interdit
    ):
        with pytest.raises(service.OAuthError) as exc:
            service.ensure_valid_redirect_uri(bad)
        assert exc.value.error == "invalid_redirect_uri"


@pytest.mark.asyncio
async def test_register_client_rejects_javascript_uri() -> None:
    with pytest.raises(service.OAuthError) as exc:
        await service.register_client(None, redirect_uris=["javascript:alert(1)"])
    assert exc.value.error == "invalid_redirect_uri"


@pytest.mark.asyncio
async def test_register_client_accepts_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service.db, "insert_client", AsyncMock())
    res = await service.register_client(None, redirect_uris=["https://claude.ai/cb"])
    assert res["client_id"].startswith("mcpc_")


@pytest.mark.asyncio
async def test_refresh_rotates(monkeypatch: pytest.MonkeyPatch) -> None:
    rotated: dict = {}

    async def fake_rotate(conn, **kw):  # noqa: ANN001, ANN003
        rotated.update(kw)

    monkeypatch.setattr(
        service.db,
        "find_apikey_by_refresh_hash",
        AsyncMock(return_value={"id": "a1", "client_id": "c1"}),
    )
    monkeypatch.setattr(service.db, "rotate_token", fake_rotate)
    res = await service.refresh(conn=None, refresh_token="r", client_id="c1")
    assert res["access_token"].startswith("mcpk_")
    assert rotated["apikey_id"] == "a1"
