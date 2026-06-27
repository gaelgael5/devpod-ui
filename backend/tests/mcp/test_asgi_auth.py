# backend/tests/mcp/test_asgi_auth.py
"""BearerGate : 401+WWW-Authenticate sans token valide, passe sinon."""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest


class _FakeCtx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *a: object) -> bool:
        return False


class _FakeEngine:
    def connect(self) -> _FakeCtx:
        return _FakeCtx()


def _patch(monkeypatch: pytest.MonkeyPatch, tenant: dict | None) -> object:
    from portal.mcp import asgi_auth

    monkeypatch.setattr(asgi_auth, "_get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(asgi_auth, "resolve_tenant", AsyncMock(return_value=tenant))
    cfg = Mock()
    cfg.server.external_url = "https://dev.yoops.org"
    monkeypatch.setattr(asgi_auth, "load_global", lambda: cfg)
    return asgi_auth


@pytest.mark.asyncio
async def test_no_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    asgi_auth = _patch(monkeypatch, None)
    sent: list = []

    async def send(m: dict) -> None:
        sent.append(m)

    inner_called: list = []

    async def inner(s: object, r: object, sd: object) -> None:
        inner_called.append(True)

    gate = asgi_auth.BearerGate(inner)
    await gate({"type": "http", "headers": []}, None, send)
    assert sent[0]["status"] == 401
    assert any(h[0] == b"www-authenticate" for h in sent[0]["headers"])
    assert not inner_called


@pytest.mark.asyncio
async def test_valid_token_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    asgi_auth = _patch(monkeypatch, {"id": "a1"})
    inner_called: list = []

    async def inner(s: object, r: object, sd: object) -> None:
        inner_called.append(True)

    async def send(m: dict) -> None:
        pass

    gate = asgi_auth.BearerGate(inner)
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer mcpk_x")]}
    await gate(scope, None, send)
    assert inner_called == [True]
