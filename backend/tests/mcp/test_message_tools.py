# backend/tests/mcp/test_message_tools.py
"""_workspace_messages : validation des arguments (bug 017)."""

from __future__ import annotations

import pytest

from portal.mcp.devpod_tools.errors import DevpodToolError
from portal.mcp.devpod_tools.message_tools import _workspace_messages


@pytest.mark.asyncio
async def test_workspace_messages_rejects_missing_workspace_as_devpod_tool_error() -> None:
    with pytest.raises(DevpodToolError):
        await _workspace_messages(None, {}, "alice")


@pytest.mark.asyncio
async def test_workspace_messages_rejects_non_numeric_limit_as_devpod_tool_error() -> None:
    with pytest.raises(DevpodToolError):
        await _workspace_messages(None, {"workspace": "app", "limit": "abc"}, "alice")


@pytest.mark.asyncio
async def test_workspace_messages_rejects_out_of_range_limit() -> None:
    # 0 est falsy en Python (`args.get("limit") or 50` retomberait sur 50) : on
    # utilise 501 pour tester la borne haute sans dépendre de ce détail préexistant.
    with pytest.raises(DevpodToolError):
        await _workspace_messages(None, {"workspace": "app", "limit": 501}, "alice")
