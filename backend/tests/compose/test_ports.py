from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.compose import ports


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
