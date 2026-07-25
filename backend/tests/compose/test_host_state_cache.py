"""Cache TTL de l'état docker LIVE d'un nœud (enabler be1112a5).

`/test-hosts/<host>/stacks` est pollé ~10 s par le front : sans cache, deux
`run_host_command` par requête (le chemin de l'incident du 24/07)."""

from __future__ import annotations

import pytest

from portal.compose import service as csvc


@pytest.fixture(autouse=True)
def _clean() -> None:
    csvc.clear_host_state_cache()
    yield
    csvc.clear_host_state_cache()


@pytest.fixture
def probe_counter(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def _stacks(node_id: str):
        calls.append(f"stacks:{node_id}")
        return [{"name": "s1", "status": "running(2)"}]

    async def _containers(node_id: str):
        calls.append(f"ps:{node_id}")
        return []

    monkeypatch.setattr(csvc, "list_host_stacks", _stacks)
    monkeypatch.setattr(csvc, "list_host_containers", _containers)
    return calls


@pytest.mark.asyncio
async def test_second_call_within_ttl_hits_cache(probe_counter: list[str]) -> None:
    r1 = await csvc.get_host_state("n1")
    r2 = await csvc.get_host_state("n1")
    assert r1 == r2
    assert r1["stacks"][0]["name"] == "s1"
    assert len(probe_counter) == 2  # stacks + ps, une seule fois


@pytest.mark.asyncio
async def test_invalidation_is_per_node(probe_counter: list[str]) -> None:
    await csvc.get_host_state("n1")
    await csvc.get_host_state("n2")
    csvc.invalidate_host_state("n1")
    await csvc.get_host_state("n1")  # re-sonde
    await csvc.get_host_state("n2")  # toujours en cache
    assert probe_counter.count("stacks:n1") == 2
    assert probe_counter.count("stacks:n2") == 1


@pytest.mark.asyncio
async def test_ttl_expiry_reprobes(
    monkeypatch: pytest.MonkeyPatch, probe_counter: list[str]
) -> None:
    monkeypatch.setattr(csvc, "_HOST_STATE_TTL_S", 0.0)
    await csvc.get_host_state("n1")
    await csvc.get_host_state("n1")
    assert probe_counter.count("stacks:n1") == 2
