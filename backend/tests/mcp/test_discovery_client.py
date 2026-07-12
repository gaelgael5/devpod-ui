"""Client HTTP d'une source de découverte MCP (probe via /auth/me)."""

from __future__ import annotations

import httpx
import pytest

from portal.mcp import discovery_client as dc
from portal.mcp.discovery_client import DiscoveryError, _api_base, probe, search


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real_client = httpx.AsyncClient  # capturé AVANT le patch (dc.httpx est le module httpx)

    def factory(*_a, **_kw):
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(dc.httpx, "AsyncClient", factory)


def test_api_base_normalisation() -> None:
    assert _api_base("https://mcp.yoops.org") == "https://mcp.yoops.org/api/v1"
    assert _api_base("https://mcp.yoops.org/") == "https://mcp.yoops.org/api/v1"
    # Idempotent si l'URL contient déjà /api/v1.
    assert _api_base("https://mcp.yoops.org/api/v1") == "https://mcp.yoops.org/api/v1"
    with pytest.raises(DiscoveryError):
        _api_base("   ")


@pytest.mark.asyncio
async def test_probe_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"name": "test1", "email": "a@b.c", "authenticated": True})

    _patch_client(monkeypatch, handler)
    out = await probe("https://mcp.yoops.org", "mcp_secret")
    assert out == {"ok": True, "name": "test1", "email": "a@b.c"}
    assert seen["url"] == "https://mcp.yoops.org/api/v1/auth/me"
    assert seen["auth"] == "Bearer mcp_secret"


@pytest.mark.asyncio
async def test_probe_401_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda r: httpx.Response(401, json={"detail": "nope"}))
    with pytest.raises(DiscoveryError, match="401"):
        await probe("https://mcp.yoops.org", "bad")


@pytest.mark.asyncio
async def test_probe_network_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    _patch_client(monkeypatch, boom)
    with pytest.raises(DiscoveryError, match="Connexion impossible"):
        await probe("https://down.example", "x")


@pytest.mark.asyncio
async def test_search_ok_normalizes_items(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 42,
                        "name": "io.github.owner/repo",
                        "description": "un serveur",
                        "transport": "stdio",
                        "category": "dev",
                        "stars": 12,
                        "repo_status": "active",
                        "source_url": "https://github.com/owner/repo",
                        "doc_url": "https://doc",
                        "parameters": [{"ignored": True}],
                    },
                    "pas-un-objet",
                ],
                "total": 1,
                "page": 2,
                "per_page": 5,
            },
        )

    _patch_client(monkeypatch, handler)
    out = await search("https://mcp.yoops.org", "mcp_key", "git", page=2, per_page=5)
    assert seen["auth"] == "Bearer mcp_key"
    assert "search_mcp" in seen["url"]
    assert "q=git" in seen["url"] and "page=2" in seen["url"] and "per_page=5" in seen["url"]
    assert out["total"] == 1 and out["page"] == 2 and out["per_page"] == 5
    # L'entrée non-objet est ignorée, l'item est normalisé (sans parameters).
    assert len(out["items"]) == 1
    it = out["items"][0]
    assert it == {
        "id": 42,
        "name": "io.github.owner/repo",
        "description": "un serveur",
        "transport": "stdio",
        "category": "dev",
        "stars": 12,
        "repo_status": "active",
        "source_url": "https://github.com/owner/repo",
        "doc_url": "https://doc",
    }


@pytest.mark.asyncio
async def test_search_401_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda r: httpx.Response(401, json={"detail": "nope"}))
    with pytest.raises(DiscoveryError, match="401"):
        await search("https://mcp.yoops.org", "bad", "x")


@pytest.mark.asyncio
async def test_search_bad_payload_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda r: httpx.Response(200, json={"nope": 1}))
    with pytest.raises(DiscoveryError, match="items"):
        await search("https://mcp.yoops.org", "k", "x")
