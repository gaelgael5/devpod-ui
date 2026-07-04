# backend/tests/routes/test_vscode_proxy.py
"""vscode_ws_proxy doit résoudre le host_port avec le même ws_id_hint que le proxy HTTP.

Sans hint, _resolve_host_port retombe sur running[0] (ordre DB arbitraire) : avec
plusieurs workspaces running, le WebSocket (Extension Host/LSP/terminal) peut se
connecter à un workspace différent de celui dont les assets HTTP ont été servis
(résolu, lui, via ?folder=). Bug 005.
"""
from __future__ import annotations

import pytest


class _FakeWebSocket:
    def __init__(self, query_string: bytes, user: dict[str, object] | None) -> None:
        self.headers: dict[str, str] = {}
        self.session: dict[str, object] = {"user": user} if user else {}
        self.scope: dict[str, object] = {"query_string": query_string}
        self.closed: tuple[int, str] | None = None

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)


@pytest.mark.asyncio
async def test_ws_proxy_passes_ws_id_hint_to_resolve_host_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import portal.routes.vscode_proxy as proxy_mod
    import portal.settings as settings_mod

    monkeypatch.setattr(
        settings_mod, "get_settings", lambda: type("S", (), {"dev_mode": True})()
    )

    captured: dict[str, object] = {}

    async def fake_resolve(login: str, ws_id_hint: str | None = None) -> int | None:
        captured["login"] = login
        captured["ws_id_hint"] = ws_id_hint
        return None  # court-circuite avant toute tentative de connexion upstream

    monkeypatch.setattr(proxy_mod, "_resolve_host_port", fake_resolve)

    ws = _FakeWebSocket(
        query_string=b"folder=/workspaces/alice-app",
        user={"login": "alice"},
    )
    await proxy_mod.vscode_ws_proxy(ws, path="")  # type: ignore[arg-type]

    assert captured["login"] == "alice"
    assert captured["ws_id_hint"] == "alice-app"
    assert ws.closed == (4503, "No active workspace")


@pytest.mark.asyncio
async def test_ws_proxy_no_hint_when_query_string_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import portal.routes.vscode_proxy as proxy_mod
    import portal.settings as settings_mod

    monkeypatch.setattr(
        settings_mod, "get_settings", lambda: type("S", (), {"dev_mode": True})()
    )

    captured: dict[str, object] = {}

    async def fake_resolve(login: str, ws_id_hint: str | None = None) -> int | None:
        captured["ws_id_hint"] = ws_id_hint
        return None

    monkeypatch.setattr(proxy_mod, "_resolve_host_port", fake_resolve)

    ws = _FakeWebSocket(query_string=b"", user={"login": "alice"})
    await proxy_mod.vscode_ws_proxy(ws, path="")  # type: ignore[arg-type]

    assert captured["ws_id_hint"] is None
