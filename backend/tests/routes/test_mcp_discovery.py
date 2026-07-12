"""Endpoints sources de découverte MCP — validation + probe."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import portal.routes.mcp_discovery as rt
from portal.mcp.discovery_client import DiscoveryError
from portal.routes.mcp_discovery import ProbeBody, SourceBody

USER = type("U", (), {"login": "alice"})()
CONN = object()
REQ = type("R", (), {"session": {"session_id": "sid-1"}})()


@pytest.fixture
def deps(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    m = AsyncMock()
    monkeypatch.setattr(rt.db, "create_source", m.create_source)
    monkeypatch.setattr(rt.db, "delete_source", m.delete_source)
    monkeypatch.setattr(rt.db, "list_sources", m.list_sources)
    monkeypatch.setattr(rt.db, "get_source", m.get_source)
    monkeypatch.setattr(rt, "reveal_secret", m.reveal_secret)
    monkeypatch.setattr(rt, "probe", m.probe)
    monkeypatch.setattr(rt, "search", m.search)
    return m


def test_source_body_validation() -> None:
    ok = SourceBody(label="Yoops", slug="yoops", url="https://mcp.yoops.org/", secret_slug="k1")
    assert ok.url == "https://mcp.yoops.org"  # trailing slash retiré
    with pytest.raises(ValidationError):
        SourceBody(label="x", slug="BAD SLUG", url="https://a")
    with pytest.raises(ValidationError):
        SourceBody(label="x", slug="ok", url="ftp://nope")


@pytest.mark.asyncio
async def test_create_returns_source(deps: AsyncMock) -> None:
    deps.create_source.return_value = {"id": 1, "label": "Yoops", "slug": "yoops"}
    body = SourceBody(label="Yoops", slug="yoops", url="https://mcp.yoops.org", secret_slug="k1")
    out = await rt.create_source_route(body=body, user=USER, conn=CONN)
    assert out["id"] == 1
    deps.create_source.assert_awaited_once_with(
        "alice", "Yoops", "yoops", "https://mcp.yoops.org", "k1", CONN
    )


@pytest.mark.asyncio
async def test_delete_missing_is_404(deps: AsyncMock) -> None:
    deps.delete_source.return_value = False
    with pytest.raises(HTTPException) as exc:
        await rt.delete_source_route(source_id=9, user=USER, conn=CONN)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_probe_resolves_secret_then_calls_client(deps: AsyncMock) -> None:
    deps.reveal_secret.return_value = "mcp_clearkey"
    deps.probe.return_value = {"ok": True, "name": "test1", "email": None}
    body = ProbeBody(url="https://mcp.yoops.org", secret_slug="k1")
    out = await rt.probe_source_route(body=body, request=REQ, user=USER, conn=CONN)
    assert out["ok"] is True
    deps.reveal_secret.assert_awaited_once_with("alice", "sid-1", "k1", CONN)
    deps.probe.assert_awaited_once_with("https://mcp.yoops.org", "mcp_clearkey")


@pytest.mark.asyncio
async def test_probe_discovery_error_is_400(deps: AsyncMock) -> None:
    deps.reveal_secret.return_value = ""
    deps.probe.side_effect = DiscoveryError("Clé refusée (401)")
    body = ProbeBody(url="https://mcp.yoops.org", secret_slug="")
    with pytest.raises(HTTPException) as exc:
        await rt.probe_source_route(body=body, request=REQ, user=USER, conn=CONN)
    assert exc.value.status_code == 400
    assert "401" in exc.value.detail
    # secret_slug vide → pas d'appel reveal_secret (clé vide directe).
    deps.reveal_secret.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_resolves_source_key_then_calls_client(deps: AsyncMock) -> None:
    deps.get_source.return_value = {"url": "https://mcp.yoops.org", "secret_slug": "k1"}
    deps.reveal_secret.return_value = "mcp_clearkey"
    deps.search.return_value = {"items": [], "total": 0, "page": 1, "per_page": 10}
    out = await rt.search_source_route(
        source_id=3, request=REQ, q="git", page=1, per_page=10, user=USER, conn=CONN
    )
    assert out["total"] == 0
    deps.get_source.assert_awaited_once_with("alice", 3, CONN)
    deps.reveal_secret.assert_awaited_once_with("alice", "sid-1", "k1", CONN)
    deps.search.assert_awaited_once_with("https://mcp.yoops.org", "mcp_clearkey", "git", 1, 10)


@pytest.mark.asyncio
async def test_search_unknown_source_is_404(deps: AsyncMock) -> None:
    deps.get_source.return_value = None
    with pytest.raises(HTTPException) as exc:
        await rt.search_source_route(
            source_id=99, request=REQ, q="x", page=1, per_page=10, user=USER, conn=CONN
        )
    assert exc.value.status_code == 404
    deps.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_discovery_error_is_400(deps: AsyncMock) -> None:
    deps.get_source.return_value = {"url": "https://mcp.yoops.org", "secret_slug": ""}
    deps.reveal_secret.return_value = ""
    deps.search.side_effect = DiscoveryError("Clé refusée (401)")
    with pytest.raises(HTTPException) as exc:
        await rt.search_source_route(
            source_id=3, request=REQ, q="x", page=1, per_page=10, user=USER, conn=CONN
        )
    assert exc.value.status_code == 400
