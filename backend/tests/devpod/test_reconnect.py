# backend/tests/devpod/test_reconnect.py
"""Reconnexion automatique d'un workspace (_reconnect_workspace).

La reconnexion (réconciliation au démarrage, portal_reload) doit rejouer la
résolution recettes/secrets/profil via start_existing_workspace — un up() nu
(recipes=None) ne régénère pas le devcontainer.json, et devpod échoue sur le
chemin uploadé de la fois précédente, supprimé après chaque up
(« devcontainer path … doesn't exist », returncode=1 en ~3 s).
"""
from __future__ import annotations

import pytest


class _FakeConn:
    pass


class _FakeConnCtx:
    async def __aenter__(self) -> _FakeConn:
        return _FakeConn()

    async def __aexit__(self, *args: object) -> bool:
        return False


class _FakeEngine:
    def connect(self) -> _FakeConnCtx:
        return _FakeConnCtx()


@pytest.mark.asyncio
async def test_reconnect_replays_full_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    import portal.devpod.service as service_mod
    import portal.routes.workspace_ops as ops_mod

    calls: list[tuple[str, str]] = []

    async def _fake_start(login: str, name: str, conn: object) -> str:
        calls.append((login, name))
        return f"{login}-{name}"

    monkeypatch.setattr(ops_mod, "start_existing_workspace", _fake_start)
    monkeypatch.setattr(service_mod, "_get_engine", lambda: _FakeEngine())

    svc = object.__new__(service_mod.DevPodService)
    await svc._reconnect_workspace("alice-app", "alice")

    assert calls == [("alice", "app")]


@pytest.mark.asyncio
async def test_reconnect_unknown_workspace_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import portal.devpod.service as service_mod
    import portal.routes.workspace_ops as ops_mod

    async def _fake_start(login: str, name: str, conn: object) -> str:
        raise ValueError(f"workspace inconnu: {name}")

    monkeypatch.setattr(ops_mod, "start_existing_workspace", _fake_start)
    monkeypatch.setattr(service_mod, "_get_engine", lambda: _FakeEngine())

    svc = object.__new__(service_mod.DevPodService)
    # Ne doit pas lever : la réconciliation continue avec les autres workspaces.
    await svc._reconnect_workspace("alice-ghost", "alice")
