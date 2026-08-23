"""Primitives MCP openapi_contract_* : registre, list (nom+url), get (id ou label)."""

from __future__ import annotations

import pytest

from portal.mcp.devpod_tools import _IMPLS
from portal.mcp.devpod_tools import contract_tools as ct
from portal.mcp.devpod_tools.errors import DevpodToolError
from portal.mcp.devpod_tools.registry import DEVPOD_PRIMITIVES

_SPEC = {
    "openapi": "3.0.0",
    "info": {"version": "2.6.1"},
    "servers": [{"url": "https://termix.yoops.org"}],
    "paths": {"/host/db/host": {"get": {"operationId": "listHosts", "summary": "Lister"}}},
}

_ROW = {
    "id": "c1",
    "label": "Termix",
    "source_url": "https://termix.yoops.org/openapi.json",
    "category": "infra",
    "version": "2.6.1",
    "raw_spec": _SPEC,
}


def test_primitives_registered_admin_scope() -> None:
    for name in ("openapi_contract_list", "openapi_contract_get"):
        assert name in DEVPOD_PRIMITIVES, name
        assert DEVPOD_PRIMITIVES[name]["scope"] == "admin"
        assert name in _IMPLS


@pytest.mark.asyncio
async def test_list_returns_name_and_url(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _list_all(conn: object) -> list[dict[str, object]]:
        return [_ROW]

    monkeypatch.setattr(ct.oc, "list_all", _list_all)
    out = await ct._contract_list(None, {}, "admin")  # type: ignore[arg-type]
    assert out == [
        {
            "id": "c1",
            "label": "Termix",
            "url": "https://termix.yoops.org/openapi.json",
            "category": "infra",
            "version": "2.6.1",
        }
    ]


@pytest.mark.asyncio
async def test_get_requires_contract() -> None:
    with pytest.raises(DevpodToolError, match="contract requis"):
        await ct._contract_get(None, {}, "admin")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_by_id_includes_servers_and_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _get(conn: object, cid: str) -> dict[str, object] | None:
        return _ROW if cid == "c1" else None

    monkeypatch.setattr(ct.oc, "get", _get)
    out = await ct._contract_get(None, {"contract": "c1"}, "admin")  # type: ignore[arg-type]
    assert out["servers"] == ["https://termix.yoops.org"]
    assert any(op["operation_id"] == "listHosts" for op in out["operations"])
    assert "raw_spec" not in out


@pytest.mark.asyncio
async def test_get_falls_back_to_label(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _get(conn: object, cid: str) -> None:
        return None

    async def _list_all(conn: object) -> list[dict[str, object]]:
        return [_ROW]

    monkeypatch.setattr(ct.oc, "get", _get)
    monkeypatch.setattr(ct.oc, "list_all", _list_all)
    out = await ct._contract_get(None, {"contract": "Termix"}, "admin")  # type: ignore[arg-type]
    assert out["id"] == "c1"


@pytest.mark.asyncio
async def test_get_unknown_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _get(conn: object, cid: str) -> None:
        return None

    async def _list_all(conn: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(ct.oc, "get", _get)
    monkeypatch.setattr(ct.oc, "list_all", _list_all)
    with pytest.raises(DevpodToolError, match="introuvable"):
        await ct._contract_get(None, {"contract": "nope"}, "admin")  # type: ignore[arg-type]
