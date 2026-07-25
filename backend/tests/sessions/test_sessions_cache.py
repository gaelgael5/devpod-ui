"""Cache TTL de l'agrégat sessions (enabler be1112a5).

Découple le polling du front de la sonde SSH réelle : à volume de polling
constant, la sonde ne part qu'à l'expiration du TTL. Invalidé sur mutation
(création/fermeture de session) pour ne jamais montrer un état périmé après
une action.
"""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

from portal.sessions import aggregate, registry


@pytest.fixture(autouse=True)
def _clean() -> None:
    registry.clear()
    aggregate.clear_sessions_cache()
    yield
    registry.clear()
    aggregate.clear_sessions_cache()


class _FakeEngine:
    @contextlib.asynccontextmanager
    async def connect(self):
        yield object()


@pytest.fixture
def probe_counter(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Environnement minimal : 1 workspace running, compte les sondes SSH."""
    monkeypatch.setattr(aggregate, "_get_engine", lambda: _FakeEngine())

    async def _fake_warm(login: str, ws_id: str, **kw: Any) -> bool:
        return True

    monkeypatch.setattr(aggregate, "warm_tunnel", _fake_warm)

    async def _refs(login: str | None, conn: Any) -> list[dict[str, Any]]:
        return [{"login": "alice", "name": "ws", "host": ""}]

    async def _statuses(*a: Any, **kw: Any) -> list[dict[str, Any]]:
        return [{"ws_id": "alice-ws", "login": "alice", "status": "running"}]

    async def _tests(login: str, conn: Any) -> list[Any]:
        return []

    probes: list[str] = []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        probes.append(ws_id)
        return 0, "main\n"

    monkeypatch.setattr(aggregate, "list_workspace_refs", _refs)
    monkeypatch.setattr(aggregate, "list_by_login_db", _statuses)
    monkeypatch.setattr(aggregate, "list_test_hosts_for_login", _tests)
    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)
    return probes


@pytest.mark.asyncio
async def test_second_call_within_ttl_does_not_probe(probe_counter: list[str]) -> None:
    r1 = await aggregate.list_sessions(login="alice", is_admin=False)
    r2 = await aggregate.list_sessions(login="alice", is_admin=False)
    assert r1 == r2
    assert len(probe_counter) == 1  # une seule sonde SSH pour deux lectures


@pytest.mark.asyncio
async def test_invalidate_forces_fresh_probe(probe_counter: list[str]) -> None:
    await aggregate.list_sessions(login="alice", is_admin=False)
    aggregate.invalidate_sessions_cache()
    await aggregate.list_sessions(login="alice", is_admin=False)
    assert len(probe_counter) == 2


@pytest.mark.asyncio
async def test_ttl_expiry_reprobes(
    monkeypatch: pytest.MonkeyPatch, probe_counter: list[str]
) -> None:
    # Neutralise AUSSI le cache par-ws sous-jacent : on observe le cache agrégat.
    monkeypatch.setattr(aggregate, "_CACHE_TTL_S", 0.0)
    monkeypatch.setattr(aggregate, "_WS_PROBE_TTL_S", 0.0)
    await aggregate.list_sessions(login="alice", is_admin=False)
    await aggregate.list_sessions(login="alice", is_admin=False)
    assert len(probe_counter) == 2


@pytest.mark.asyncio
async def test_cache_key_isolates_logins(
    monkeypatch: pytest.MonkeyPatch, probe_counter: list[str]
) -> None:
    """Le cache AGRÉGAT est par login (pas de fuite du résultat d'alice vers bob).

    La sonde par-ws sous-jacente est neutralisée : elle est volontairement
    partagée par ws_id, ce qui masquerait l'observation.
    """
    monkeypatch.setattr(aggregate, "_WS_PROBE_TTL_S", 0.0)
    await aggregate.list_sessions(login="alice", is_admin=False)
    await aggregate.list_sessions(login="bob", is_admin=False)
    assert len(probe_counter) == 2


# ─── Sonde par-workspace (route GET /me/workspaces/{name}/sessions) ──────────


@pytest.mark.asyncio
async def test_ws_probe_cached_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        calls.append(ws_id)
        return 0, "s1\ns2\n"

    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)
    r1 = await aggregate.probe_workspace_sessions("alice", "alice-ws")
    r2 = await aggregate.probe_workspace_sessions("alice", "alice-ws")
    assert r1 == r2 == (0, ["s1", "s2"])
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_ws_probe_caches_failures_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un rc d'échec est aussi caché : pas de marteau SSH sur un host mort."""
    calls: list[str] = []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        calls.append(ws_id)
        return 255, "connexion refusée"

    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)
    r1 = await aggregate.probe_workspace_sessions("alice", "alice-ws")
    r2 = await aggregate.probe_workspace_sessions("alice", "alice-ws")
    assert r1 == r2 == (255, [])
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_ws_probe_invalidated_on_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0):
        calls.append(ws_id)
        return 0, "main\n"

    monkeypatch.setattr(aggregate, "ws_exec", _ws_exec)
    await aggregate.probe_workspace_sessions("alice", "alice-ws")
    aggregate.invalidate_sessions_cache()
    await aggregate.probe_workspace_sessions("alice", "alice-ws")
    assert len(calls) == 2
