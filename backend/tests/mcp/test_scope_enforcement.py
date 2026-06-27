# backend/tests/mcp/test_scope_enforcement.py
"""Enforcement par scope dans _resolve_target (spec 24 §4)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from portal.mcp import aggregator


def _setup(monkeypatch: pytest.MonkeyPatch, *, grant_scopes, prim_scope, original="workspace_stop"):
    grant = {
        "enabled": True,
        "backend_id": "devpod-admin",
        "backend_key_id": None,
        "expose_mode": "all",
        "expose": [],
        "scopes": grant_scopes,
    }
    backend = {"enabled": True, "namespace": "devpod", "url": "", "transport": "internal"}
    prim = {
        "original_name": original,
        "quarantined": False,
        "definition": {"scope": prim_scope} if prim_scope else {},
    }
    monkeypatch.setattr(aggregator, "list_grants", AsyncMock(return_value=[grant]))
    monkeypatch.setattr(aggregator, "get_backend", AsyncMock(return_value=backend))
    monkeypatch.setattr(aggregator, "list_primitives", AsyncMock(return_value=[prim]))


async def _resolve(original="workspace_stop"):
    return await aggregator.resolve_call(
        None, apikey_id="k", owner_login="admin",
        namespaced_name=f"devpod__{original}", kind="tool",
    )


@pytest.mark.asyncio
async def test_scope_not_granted_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, grant_scopes=["read"], prim_scope="admin")
    assert await _resolve() is None


@pytest.mark.asyncio
async def test_scope_granted_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, grant_scopes=["read", "admin"], prim_scope="admin")
    target = await _resolve()
    assert target is not None
    assert target.transport == "internal"


@pytest.mark.asyncio
async def test_null_scopes_no_enforcement(monkeypatch: pytest.MonkeyPatch) -> None:
    # Rétrocompat backends externes : grant.scopes NULL → pas d'enforcement.
    _setup(monkeypatch, grant_scopes=None, prim_scope="admin")
    assert await _resolve() is not None


@pytest.mark.asyncio
async def test_primitive_without_scope_not_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    # Une primitive sans scope déclaré n'est jamais bloquée par les scopes du grant.
    _setup(monkeypatch, grant_scopes=["read"], prim_scope=None)
    assert await _resolve() is not None


@pytest.mark.asyncio
async def test_aggregate_lists_only_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    # tools/list (aggregate_primitives) ne montre que les primitives appelables par scope.
    grant = {
        "enabled": True, "backend_id": "devpod-admin", "backend_key_id": None,
        "expose_mode": "all", "expose": [], "scopes": ["read"],
    }
    backend = {"enabled": True, "namespace": "devpod", "url": "", "transport": "internal"}
    prims = [
        {"original_name": "workspace_list", "quarantined": False, "definition": {"scope": "read"}},
        {"original_name": "workspace_stop", "quarantined": False, "definition": {"scope": "admin"}},
    ]
    monkeypatch.setattr(aggregator, "list_grants", AsyncMock(return_value=[grant]))
    monkeypatch.setattr(aggregator, "get_backend", AsyncMock(return_value=backend))
    monkeypatch.setattr(aggregator, "list_primitives", AsyncMock(return_value=prims))
    res = await aggregator.aggregate_primitives(
        None, apikey_id="k", owner_login="admin", kind="tool"
    )
    names = [p.original_name for p in res]
    assert "workspace_list" in names
    assert "workspace_stop" not in names
