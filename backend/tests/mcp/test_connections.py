from __future__ import annotations

import pytest

from portal.mcp.connections import BackendUnavailable, open_session


async def test_open_session_unreachable_raises_backend_unavailable() -> None:
    # port fermé / hôte injoignable → BackendUnavailable, pas une exception brute
    with pytest.raises(BackendUnavailable):
        async with open_session("http://127.0.0.1:1/mcp", timeout_s=2.0):
            pass


# ---------------------------------------------------------------------------
# Settle post-initialize du transport SSE (race de dispatch, ex. docflow)
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.initialized = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def initialize(self) -> None:
        self.initialized = True


def _patch_transports(monkeypatch, *, calls: list[str]):
    """Remplace sse_client/streamable_http_client/ClientSession et enregistre
    l'ordre des événements (initialize, sleep) pour vérifier le settle."""
    from contextlib import asynccontextmanager

    import portal.mcp.connections as mod

    @asynccontextmanager
    async def fake_sse(url, **kw):
        yield ("r", "w")

    @asynccontextmanager
    async def fake_http(url, **kw):
        yield ("r", "w", lambda: None)

    def fake_client_session(read, write):
        sess = _FakeSession()
        _orig_init = sess.initialize

        async def _init():
            await _orig_init()
            calls.append("initialize")

        sess.initialize = _init  # type: ignore[method-assign]
        return sess

    async def fake_sleep(d):
        calls.append(f"sleep:{d}")

    monkeypatch.setattr(mod, "sse_client", fake_sse)
    monkeypatch.setattr(mod, "streamable_http_client", fake_http)
    monkeypatch.setattr(mod, "create_mcp_http_client", lambda **kw: _NullAsyncCtx())
    monkeypatch.setattr(mod, "ClientSession", fake_client_session)
    monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)


class _NullAsyncCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def test_sse_settles_after_initialize(monkeypatch) -> None:
    """Transport sse : un sleep(settle) suit initialize, avant le yield."""
    calls: list[str] = []
    _patch_transports(monkeypatch, calls=calls)
    async with open_session("http://x/sse", transport="sse", sse_init_settle_s=0.5):
        pass
    assert calls == ["initialize", "sleep:0.5"]


async def test_sse_settle_zero_skips_sleep(monkeypatch) -> None:
    calls: list[str] = []
    _patch_transports(monkeypatch, calls=calls)
    async with open_session("http://x/sse", transport="sse", sse_init_settle_s=0.0):
        pass
    assert calls == ["initialize"]


async def test_streamable_http_never_settles(monkeypatch) -> None:
    """Le settle ne concerne que sse : streamable_http n'attend jamais."""
    calls: list[str] = []
    _patch_transports(monkeypatch, calls=calls)
    async with open_session("http://x/mcp", transport="streamable_http", sse_init_settle_s=5.0):
        pass
    assert calls == ["initialize"]


async def test_sse_settle_defaults_to_settings(monkeypatch) -> None:
    """Sans paramètre explicite, le settle vient de mcp_sse_init_settle_s."""
    calls: list[str] = []
    _patch_transports(monkeypatch, calls=calls)
    monkeypatch.setattr("portal.mcp.connections._sse_init_settle_s", lambda: 0.25)
    async with open_session("http://x/sse", transport="sse"):
        pass
    assert calls == ["initialize", "sleep:0.25"]


# ---------------------------------------------------------------------------
# Schéma d'authentification : header injecté selon auth_scheme
# ---------------------------------------------------------------------------


def _capture_http_headers(monkeypatch) -> dict[str, dict[str, str] | None]:
    """Patche le transport streamable_http et capture le header d'auth transmis."""
    from contextlib import asynccontextmanager

    import portal.mcp.connections as mod

    captured: dict[str, dict[str, str] | None] = {}

    def fake_create_http_client(**kw):
        captured["headers"] = kw.get("headers")
        return _NullAsyncCtx()

    @asynccontextmanager
    async def fake_http(url, **kw):
        yield ("r", "w", lambda: None)

    monkeypatch.setattr(mod, "create_mcp_http_client", fake_create_http_client)
    monkeypatch.setattr(mod, "streamable_http_client", fake_http)
    monkeypatch.setattr(mod, "ClientSession", lambda read, write: _FakeSession())
    return captured


async def test_auth_scheme_bearer_sends_authorization_header(monkeypatch) -> None:
    captured = _capture_http_headers(monkeypatch)
    async with open_session("http://x/mcp", bearer="s3cr3t", auth_scheme="bearer"):
        pass
    assert captured["headers"] == {"Authorization": "Bearer s3cr3t"}


async def test_auth_scheme_x_api_key_sends_x_api_key_header(monkeypatch) -> None:
    captured = _capture_http_headers(monkeypatch)
    async with open_session("http://x/mcp", bearer="s3cr3t", auth_scheme="x_api_key"):
        pass
    assert captured["headers"] == {"X-API-Key": "s3cr3t"}


async def test_auth_scheme_defaults_to_bearer(monkeypatch) -> None:
    captured = _capture_http_headers(monkeypatch)
    async with open_session("http://x/mcp", bearer="s3cr3t"):
        pass
    assert captured["headers"] == {"Authorization": "Bearer s3cr3t"}


async def test_no_bearer_sends_no_auth_header(monkeypatch) -> None:
    captured = _capture_http_headers(monkeypatch)
    async with open_session("http://x/mcp", auth_scheme="x_api_key"):
        pass
    assert captured["headers"] is None


async def test_extra_headers_merged_with_auth(monkeypatch) -> None:
    """Les en-têtes on-behalf-of s'ajoutent à l'auth, sans l'écraser."""
    captured = _capture_http_headers(monkeypatch)
    async with open_session(
        "http://x/mcp", bearer="s3cr3t", extra_headers={"x-portal-actor": "alice"}
    ):
        pass
    assert captured["headers"] == {
        "Authorization": "Bearer s3cr3t",
        "x-portal-actor": "alice",
    }


async def test_extra_headers_without_bearer(monkeypatch) -> None:
    captured = _capture_http_headers(monkeypatch)
    async with open_session("http://x/mcp", extra_headers={"x-portal-actor": "alice"}):
        pass
    assert captured["headers"] == {"x-portal-actor": "alice"}
