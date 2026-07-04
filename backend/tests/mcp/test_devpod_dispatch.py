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


@pytest.mark.asyncio
async def test_unhandled_exception_becomes_iserror_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug 017 : une exception non-DevpodToolError (bug d'impl, ex. ValueError d'un
    int() non validé) doit rester dans le CallToolResult — sinon elle contourne
    audit_record côté execute_tool_call (handlers.py)."""

    async def boom(conn, args, login):  # noqa: ANN001, ANN202
        raise ValueError("abc n'est pas un entier")

    monkeypatch.setitem(devpod_tools._IMPLS, "y", boom)
    res = await devpod_tools.execute_internal_tool(None, "y", {}, owner_login="admin")
    assert res.isError
    assert "erreur interne" in res.content[0].text


def test_optional_int_rejects_non_numeric_as_devpod_tool_error() -> None:
    with pytest.raises(devpod_tools.DevpodToolError):
        devpod_tools._optional_int({"lines": "abc"}, "lines", 200)


def test_optional_int_returns_default_when_missing() -> None:
    assert devpod_tools._optional_int({}, "lines", 200) == 200
