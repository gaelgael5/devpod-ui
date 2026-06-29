# backend/tests/mcp/test_devpod_portal.py
"""portal_reload + cohérence registre ↔ implémentations."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from portal.mcp import devpod_tools
from portal.mcp.devpod_tools.registry import DEVPOD_PRIMITIVES


@pytest.mark.asyncio
async def test_portal_reload_container_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conteneur running → reconnexion lancée, reconnected=True."""
    svc = SimpleNamespace(
        status=AsyncMock(return_value={"status": "running"}),
        reconnect=MagicMock(),
    )
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)
    res = await devpod_tools._portal_reload(None, {"workspace": "dev"}, "admin")
    assert res == {"workspace": "dev", "reconnected": True, "reason": None}
    svc.reconnect.assert_called_once_with("admin", "admin-dev")


@pytest.mark.asyncio
async def test_portal_reload_container_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conteneur non running → reconnexion refusée, reason='container_down'."""
    for bad_status in ("stopped", "unknown", "error", ""):
        svc = SimpleNamespace(
            status=AsyncMock(return_value={"status": bad_status}),
            reconnect=MagicMock(),
        )
        monkeypatch.setattr(devpod_tools, "get_service", lambda s=svc: s)
        res = await devpod_tools._portal_reload(None, {"workspace": "dev"}, "admin")
        assert res == {"workspace": "dev", "reconnected": False, "reason": "container_down"}, bad_status
        svc.reconnect.assert_not_called()


@pytest.mark.asyncio
async def test_portal_reload_node_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exception lors de la lecture du statut → reason='node_unreachable', pas d'exception propagée."""
    svc = SimpleNamespace(
        status=AsyncMock(side_effect=RuntimeError("db down")),
        reconnect=MagicMock(),
    )
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)
    res = await devpod_tools._portal_reload(None, {"workspace": "dev"}, "admin")
    assert res == {"workspace": "dev", "reconnected": False, "reason": "node_unreachable"}
    svc.reconnect.assert_not_called()


def test_registry_and_impls_match() -> None:
    assert set(DEVPOD_PRIMITIVES) == set(devpod_tools._IMPLS)
    assert len(DEVPOD_PRIMITIVES) == 44


def test_every_primitive_has_valid_scope_and_schema() -> None:
    valid = {"read", "write", "exec", "admin"}
    for name, defn in DEVPOD_PRIMITIVES.items():
        assert defn["scope"] in valid, name
        assert "description" in defn and "inputSchema" in defn, name
        assert defn["inputSchema"]["type"] == "object", name
