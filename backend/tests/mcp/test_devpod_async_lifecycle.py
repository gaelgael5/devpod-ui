# backend/tests/mcp/test_devpod_async_lifecycle.py
"""Tests de la primitive workspace_create (spec 25 §B)."""
from __future__ import annotations

import pytest

from portal.mcp import devpod_tools


@pytest.mark.asyncio
async def test_workspace_create_launches_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_launch(kind: str, workspace: str, owner_login: str, work: object) -> str:
        captured.update(kind=kind, workspace=workspace, owner=owner_login)
        return "f" * 32

    monkeypatch.setattr(devpod_tools.operations, "launch_operation", fake_launch)
    res = await devpod_tools._workspace_create(
        None, {"name": "dev", "repo": "git@x/y.git"}, "alice"
    )
    assert res == {"operation_id": "f" * 32}
    assert captured == {"kind": "workspace_create", "workspace": "dev", "owner": "alice"}


@pytest.mark.asyncio
async def test_workspace_create_requires_name_and_repo() -> None:
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_create(None, {"name": "dev"}, "alice")


@pytest.mark.asyncio
async def test_workspace_delete_requires_confirm() -> None:
    with pytest.raises(devpod_tools.DevpodToolError, match="confirm"):
        await devpod_tools._workspace_delete(None, {"workspace": "dev", "confirm": False}, "alice")


@pytest.mark.asyncio
async def test_workspace_delete_launches_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devpod_tools.operations, "launch_operation",
                        lambda kind, ws, owner, work: "a" * 32)
    res = await devpod_tools._workspace_delete(None, {"workspace": "dev", "confirm": True}, "alice")
    assert res == {"operation_id": "a" * 32}


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm_value,include_key", [
    (1, True),
    ("true", True),
    (None, False),  # missing key
])
async def test_workspace_delete_refuses_truthy_non_true(
    confirm_value: object, include_key: bool
) -> None:
    """Verify that confirm must be exactly True, not just truthy."""
    args = {"workspace": "dev"}
    if include_key:
        args["confirm"] = confirm_value

    with pytest.raises(devpod_tools.DevpodToolError, match="confirm"):
        await devpod_tools._workspace_delete(None, args, "alice")
