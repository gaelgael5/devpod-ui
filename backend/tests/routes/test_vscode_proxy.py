# backend/tests/routes/test_vscode_proxy.py
"""Résolution workspace du proxy VS Code (mode vs_portal, domaine partagé).

Bug « tous les workspaces ouvrent le même » : seule la requête HTML d'entrée
porte ?folder= ; les assets et surtout les WebSockets (la vraie session
VS Code) arrivaient sans hint et retombaient sur running[0] — ordre de table
arbitraire, donc le même workspace pour tout le monde, y compris à la place
d'un workspace explicitement demandé mais introuvable.

Résolution stricte désormais : hint explicite (?ws= / ?folder=) > cookie de
liaison posé à l'entrée > unique workspace running — jamais de repli
arbitraire, et un hint sans correspondance échoue plutôt que de servir un
autre workspace.
"""
from __future__ import annotations

import time
from typing import Any

import pytest

import portal.routes.vscode_proxy as proxy_mod
from portal.routes.vscode_proxy import _resolve_workspace, _ws_id_hint_from_query


class _FakeConn:
    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeEngine:
    def begin(self) -> _FakeConn:
        return _FakeConn()


@pytest.fixture
def ws_rows(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    async def fake_list(login: str, conn: Any) -> list[dict[str, Any]]:
        return rows

    monkeypatch.setattr(proxy_mod, "_get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(proxy_mod, "list_by_login_db", fake_list)
    return rows


def _row(ws_id: str, port: int | None, status: str = "running") -> dict[str, Any]:
    return {"ws_id": ws_id, "status": status, "host_port": port}


# ─── _ws_id_hint_from_query ───────────────────────────────────────────────────


def test_hint_ws_param_takes_precedence() -> None:
    assert (
        _ws_id_hint_from_query("folder=/workspaces/alice-other&ws=alice-app") == "alice-app"
    )


def test_hint_derived_from_folder() -> None:
    assert _ws_id_hint_from_query("folder=/workspaces/alice-app") == "alice-app"


def test_hint_from_urlencoded_folder() -> None:
    """parse_qs décode %2F — l'ancien découpage manuel ratait ce cas."""
    assert _ws_id_hint_from_query("folder=%2Fworkspaces%2Falice-app") == "alice-app"


def test_hint_absent_for_multi_source_folder() -> None:
    """Workspace multi-sources : folder=/workspaces sans ws_id → pas de hint."""
    assert _ws_id_hint_from_query("folder=/workspaces") is None
    assert _ws_id_hint_from_query("reconnectionToken=abc") is None


# ─── _resolve_workspace ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_hint_selects_the_requested_workspace(ws_rows) -> None:
    ws_rows.extend([_row("alice-roles", 40007), _row("alice-app", 40001)])
    assert await _resolve_workspace("alice", "alice-app", None) == ("alice-app", 40001)


@pytest.mark.asyncio
async def test_resolve_hint_without_match_never_serves_another_workspace(ws_rows) -> None:
    """Workspace demandé arrêté/inconnu → échec, PAS running[0]."""
    ws_rows.extend([_row("alice-roles", 40007), _row("alice-app", None, status="stopped")])
    assert await _resolve_workspace("alice", "alice-app", None) is None


@pytest.mark.asyncio
async def test_resolve_falls_back_to_binding_cookie(ws_rows) -> None:
    """Sous-requête sans hint (asset, WebSocket) : le cookie de liaison décide."""
    ws_rows.extend([_row("alice-roles", 40007), _row("alice-app", 40001)])
    assert await _resolve_workspace("alice", None, "alice-app") == ("alice-app", 40001)


@pytest.mark.asyncio
async def test_resolve_ignores_stale_cookie(ws_rows) -> None:
    ws_rows.extend([_row("alice-roles", 40007), _row("alice-app", 40001)])
    assert await _resolve_workspace("alice", None, "alice-gone") is None


@pytest.mark.asyncio
async def test_resolve_single_running_without_any_hint(ws_rows) -> None:
    ws_rows.append(_row("alice-app", 40001))
    assert await _resolve_workspace("alice", None, None) == ("alice-app", 40001)


@pytest.mark.asyncio
async def test_resolve_ambiguous_without_hint_fails(ws_rows) -> None:
    """Plusieurs running, ni hint ni cookie → jamais de choix arbitraire."""
    ws_rows.extend([_row("alice-roles", 40007), _row("alice-app", 40001)])
    assert await _resolve_workspace("alice", None, None) is None


# ─── vscode_ws_proxy (handler WebSocket) ─────────────────────────────────────


class _FakeWebSocket:
    def __init__(
        self,
        query_string: bytes,
        user: dict[str, object] | None,
        cookies: dict[str, str] | None = None,
    ) -> None:
        self.headers: dict[str, str] = {}
        self.session: dict[str, object] = (
            {"user": user, "auth_time": int(time.time())} if user else {}
        )
        self.scope: dict[str, object] = {"query_string": query_string}
        self.cookies: dict[str, str] = cookies or {}
        self.closed: tuple[int, str] | None = None

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)


@pytest.fixture
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    import portal.settings as settings_mod

    monkeypatch.setattr(
        settings_mod, "get_settings", lambda: type("S", (), {"dev_mode": True})()
    )


@pytest.mark.asyncio
async def test_ws_proxy_resolves_with_hint_and_cookie(
    _dev_mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_resolve(
        login: str, ws_id_hint: str | None, cookie_ws_id: str | None
    ) -> tuple[str, int] | None:
        captured["login"] = login
        captured["ws_id_hint"] = ws_id_hint
        captured["cookie_ws_id"] = cookie_ws_id
        return None  # court-circuite avant toute connexion upstream

    monkeypatch.setattr(proxy_mod, "_resolve_workspace", fake_resolve)

    ws = _FakeWebSocket(
        query_string=b"folder=/workspaces/alice-app",
        user={"login": "alice"},
        cookies={"vsproxy_ws": "alice-other"},
    )
    await proxy_mod.vscode_ws_proxy(ws, path="")  # type: ignore[arg-type]

    assert captured["login"] == "alice"
    assert captured["ws_id_hint"] == "alice-app"
    assert captured["cookie_ws_id"] == "alice-other"
    assert ws.closed == (4503, "No active workspace")


@pytest.mark.asyncio
async def test_ws_proxy_uses_cookie_when_query_has_no_hint(
    _dev_mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_resolve(
        login: str, ws_id_hint: str | None, cookie_ws_id: str | None
    ) -> tuple[str, int] | None:
        captured["ws_id_hint"] = ws_id_hint
        captured["cookie_ws_id"] = cookie_ws_id
        return None

    monkeypatch.setattr(proxy_mod, "_resolve_workspace", fake_resolve)

    ws = _FakeWebSocket(
        query_string=b"reconnectionToken=abc",
        user={"login": "alice"},
        cookies={"vsproxy_ws": "alice-app"},
    )
    await proxy_mod.vscode_ws_proxy(ws, path="")  # type: ignore[arg-type]

    assert captured["ws_id_hint"] is None
    assert captured["cookie_ws_id"] == "alice-app"
