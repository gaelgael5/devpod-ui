# backend/tests/mcp/test_devpod_portal.py
"""portal_reload + cohérence registre ↔ implémentations (les 16 primitives spec 24)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from portal.mcp import devpod_tools
from portal.mcp.devpod_tools.registry import DEVPOD_PRIMITIVES


@pytest.mark.asyncio
async def test_portal_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = SimpleNamespace(reconnect=MagicMock())
    monkeypatch.setattr(devpod_tools, "get_service", lambda: svc)
    res = await devpod_tools._portal_reload(None, {"workspace": "dev"}, "admin")
    assert res == {"workspace": "dev", "reconnected": True}
    svc.reconnect.assert_called_once_with("admin", "admin-dev")


def test_registry_and_impls_match() -> None:
    assert set(DEVPOD_PRIMITIVES) == set(devpod_tools._IMPLS)
    assert len(DEVPOD_PRIMITIVES) == 23


def test_every_primitive_has_valid_scope_and_schema() -> None:
    valid = {"read", "write", "exec", "admin"}
    for name, defn in DEVPOD_PRIMITIVES.items():
        assert defn["scope"] in valid, name
        assert "description" in defn and "inputSchema" in defn, name
        assert defn["inputSchema"]["type"] == "object", name
