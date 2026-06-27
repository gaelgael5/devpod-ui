# backend/tests/mcp/test_devpod_paths.py
"""Confinement des chemins workspace (spec 24 I-5)."""
from __future__ import annotations

import pytest

from portal.mcp.devpod_tools.errors import DevpodToolError
from portal.mcp.devpod_tools.paths import safe_workspace_path


def test_dot_is_root() -> None:
    assert safe_workspace_path("w", ".") == "/workspaces/w"


def test_empty_is_root() -> None:
    assert safe_workspace_path("w", "") == "/workspaces/w"


def test_relative_path() -> None:
    assert safe_workspace_path("w", "src/a.py") == "/workspaces/w/src/a.py"


def test_inner_dotdot_stays_inside() -> None:
    assert safe_workspace_path("w", "a/../b") == "/workspaces/w/b"


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/../../b", "../../w/x", "a\0b"])
def test_escapes_rejected(bad: str) -> None:
    with pytest.raises(DevpodToolError):
        safe_workspace_path("w", bad)
