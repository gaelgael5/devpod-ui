from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.compose import ports
from portal.compose.port_aliases import PortAlias


def test_suggest_free_port() -> None:
    assert ports.suggest_free_port({3000, 3001}, start=3000, end=3002) == 3002
    assert ports.suggest_free_port({3000, 3001, 3002}, start=3000, end=3002) is None


@pytest.mark.asyncio
async def test_check_ports_conflict_raises_with_suggestion(monkeypatch) -> None:
    monkeypatch.setattr(ports, "conflicting_ports", AsyncMock(return_value={3000}))
    monkeypatch.setattr(ports, "_live_used_ports", AsyncMock(return_value=set()))
    host = SimpleNamespace(name="n1", type="ssh")
    with pytest.raises(ports.PortConflict) as exc:
        await ports.check_ports(None, host, "n1", [3000])
    assert exc.value.conflicts == {3000}
    assert exc.value.suggestion is not None


@pytest.mark.asyncio
async def test_check_ports_ok(monkeypatch) -> None:
    monkeypatch.setattr(ports, "conflicting_ports", AsyncMock(return_value=set()))
    monkeypatch.setattr(ports, "_live_used_ports", AsyncMock(return_value=set()))
    host = SimpleNamespace(name="n1", type="ssh")
    await ports.check_ports(None, host, "n1", [3000])  # ne lève pas


@pytest.mark.asyncio
async def test_check_ports_live_conflict_raises(monkeypatch) -> None:
    monkeypatch.setattr(ports, "conflicting_ports", AsyncMock(return_value=set()))
    monkeypatch.setattr(ports, "_live_used_ports", AsyncMock(return_value={3000}))
    host = SimpleNamespace(name="n1", type="ssh")
    with pytest.raises(ports.PortConflict) as exc:
        await ports.check_ports(None, host, "n1", [3000])
    assert exc.value.conflicts == {3000}
    assert exc.value.suggestion is not None


@pytest.mark.asyncio
async def test_check_ports_empty_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(ports, "conflicting_ports", AsyncMock(return_value=set()))
    monkeypatch.setattr(ports, "_live_used_ports", AsyncMock(return_value=set()))
    host = SimpleNamespace(name="n1", type="ssh")
    await ports.check_ports(None, host, "n1", [])  # ne lève pas


# ---------------------------------------------------------------------------
# allocate_ports
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allocate_ports_basic(monkeypatch) -> None:
    """Alloue le premier port libre ≥ min_host_port."""
    monkeypatch.setattr(ports, "used_ports_on_node", AsyncMock(return_value=set()))
    monkeypatch.setattr(ports, "_live_used_ports", AsyncMock(return_value=set()))
    host = SimpleNamespace(name="n1", type="ssh")
    aliases = [PortAlias(alias="web", min_host_port=3000, container_port=80)]
    result = await ports.allocate_ports(None, host, "n1", aliases)
    assert result == {"web": 3000}


@pytest.mark.asyncio
async def test_allocate_ports_skips_occupied(monkeypatch) -> None:
    """Saute les ports déjà occupés en DB et live."""
    monkeypatch.setattr(ports, "used_ports_on_node", AsyncMock(return_value={3000, 3001}))
    monkeypatch.setattr(ports, "_live_used_ports", AsyncMock(return_value={3002}))
    host = SimpleNamespace(name="n1", type="ssh")
    aliases = [PortAlias(alias="web", min_host_port=3000, container_port=80)]
    result = await ports.allocate_ports(None, host, "n1", aliases)
    assert result == {"web": 3003}


@pytest.mark.asyncio
async def test_allocate_ports_sequential_no_collision(monkeypatch) -> None:
    """Deux alias dans le même appel ne se voient pas allouer le même port."""
    monkeypatch.setattr(ports, "used_ports_on_node", AsyncMock(return_value=set()))
    monkeypatch.setattr(ports, "_live_used_ports", AsyncMock(return_value=set()))
    host = SimpleNamespace(name="n1", type="ssh")
    aliases = [
        PortAlias(alias="browser", min_host_port=3000, container_port=3000),
        PortAlias(alias="api", min_host_port=3000, container_port=8080),
    ]
    result = await ports.allocate_ports(None, host, "n1", aliases)
    assert result["browser"] != result["api"]
    assert result["browser"] == 3000
    assert result["api"] == 3001  # 3000 déjà réservé par browser


@pytest.mark.asyncio
async def test_allocate_ports_raises_when_range_exhausted(monkeypatch) -> None:
    occupied = set(range(3000, 10000))
    monkeypatch.setattr(ports, "used_ports_on_node", AsyncMock(return_value=occupied))
    monkeypatch.setattr(ports, "_live_used_ports", AsyncMock(return_value=set()))
    host = SimpleNamespace(name="n1", type="ssh")
    aliases = [PortAlias(alias="web", min_host_port=3000, container_port=80)]
    with pytest.raises(ports.PortConflict):
        await ports.allocate_ports(None, host, "n1", aliases)
