# backend/tests/mcp/test_devpod_dispatch.py
"""Dispatch du backend interne devpod (execute_internal_tool)."""
from __future__ import annotations

import json

import pytest
from mcp.shared.exceptions import McpError

from portal.mcp import devpod_tools


@pytest.mark.asyncio
async def test_unknown_tool_raises_mcperror() -> None:
    with pytest.raises(McpError):
        await devpod_tools.execute_internal_tool(None, "nope", {}, owner_login="admin")


@pytest.mark.asyncio
async def test_business_error_becomes_iserror(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(conn, args, login):  # noqa: ANN001, ANN202
        raise devpod_tools.DevpodToolError("workspace introuvable")

    monkeypatch.setitem(devpod_tools._IMPLS, "x", boom)
    res = await devpod_tools.execute_internal_tool(None, "x", {}, owner_login="admin")
    assert res.isError
    assert res.content[0].text == "workspace introuvable"


@pytest.mark.asyncio
async def test_ok_result_is_json(monkeypatch: pytest.MonkeyPatch) -> None:
    async def good(conn, args, login):  # noqa: ANN001, ANN202
        return {"hello": "world"}

    monkeypatch.setitem(devpod_tools._IMPLS, "g", good)
    res = await devpod_tools.execute_internal_tool(None, "g", {}, owner_login="admin")
    assert not res.isError
    assert json.loads(res.content[0].text) == {"hello": "world"}
