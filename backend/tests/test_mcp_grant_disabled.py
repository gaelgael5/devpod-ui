# backend/tests/test_mcp_grant_disabled.py
"""Effet runtime de la désactivation d'un service accordé (grant.enabled=False)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from portal.mcp import aggregator


def _grant(enabled: bool) -> dict[str, object]:
    return {
        "apikey_id": "ak",
        "backend_id": "b1",
        "backend_key_id": None,
        "expose_mode": "all",
        "expose": [],
        "enabled": enabled,
    }


_BACKEND = {
    "id": "b1", "owner_login": "u", "namespace": "ns", "name": "n",
    "url": "https://x", "transport": "streamable_http", "enabled": True,
}
_PRIM = {"original_name": "tool", "definition": {"x": 1}, "quarantined": False}


def _mocks(grant_enabled: bool):
    return (
        patch.object(aggregator, "list_grants", AsyncMock(return_value=[_grant(grant_enabled)])),
        patch.object(aggregator, "get_backend", AsyncMock(return_value=_BACKEND)),
        patch.object(aggregator, "list_primitives", AsyncMock(return_value=[_PRIM])),
    )


@pytest.mark.asyncio
async def test_aggregate_skips_disabled_grant() -> None:
    g, b, p = _mocks(False)
    with g, b, p:
        out = await aggregator.aggregate_primitives(
            None, apikey_id="ak", owner_login="u", kind="tool"
        )
    assert out == []


@pytest.mark.asyncio
async def test_aggregate_includes_enabled_grant() -> None:
    g, b, p = _mocks(True)
    with g, b, p:
        out = await aggregator.aggregate_primitives(
            None, apikey_id="ak", owner_login="u", kind="tool"
        )
    assert [o.original_name for o in out] == ["tool"]


@pytest.mark.asyncio
async def test_resolve_target_denies_disabled_grant() -> None:
    g, b, p = _mocks(False)
    with g, b, p:
        target = await aggregator._resolve_target(
            None, apikey_id="ak", owner_login="u", namespace="ns", original="tool", kind="tool"
        )
    assert target is None
