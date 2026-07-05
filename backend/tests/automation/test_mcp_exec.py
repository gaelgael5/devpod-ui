"""Décodage des retours d'outils MCP côté moteur de règles."""

from __future__ import annotations

import pytest
from mcp.types import CallToolResult, TextContent

from portal.automation.engine import AutomationError
from portal.automation.mcp_exec import _result_payload


def _result(text: str, *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=is_error)


def test_json_decode() -> None:
    assert _result_payload(_result('[{"slug": "ws1"}]')) == [{"slug": "ws1"}]


def test_texte_brut_conserve() -> None:
    assert _result_payload(_result("pas du json")) == "pas du json"


def test_is_error_leve() -> None:
    with pytest.raises(AutomationError):
        _result_payload(_result("boom", is_error=True))
