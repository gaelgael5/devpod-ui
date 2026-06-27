# backend/tests/devpod/test_provision.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.devpod import provision


@pytest.mark.asyncio
async def test_provision_workspace_calls_up(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = SimpleNamespace(up=AsyncMock(return_value="alice-dev"))
    monkeypatch.setattr(provision, "_get_service", lambda: svc)
    monkeypatch.setattr(provision, "_resolve_recipes_and_secrets", AsyncMock(return_value=([], {})))
    monkeypatch.setattr(provision, "_load_profile", AsyncMock(return_value=None))
    params = provision.ProvisionParams(name="dev", source="git@x/y.git", recipes=[])
    ws_id = await provision.provision_workspace("alice", params, conn=None)
    assert ws_id == "alice-dev"
    svc.up.assert_awaited_once()
