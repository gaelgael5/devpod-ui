"""Tests ownership helper _require_owned (pur, sans TestClient)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.routes import compose as r


@pytest.mark.asyncio
async def test_require_owned_forbids_foreign(monkeypatch) -> None:
    dep = SimpleNamespace(id="d1", owner_login="bob")
    monkeypatch.setattr(r.cdb, "get_deployment", AsyncMock(return_value=dep))
    user = SimpleNamespace(login="alice", roles=["dev"])
    with pytest.raises(r.HTTPException) as exc:
        await r._require_owned(None, "d1", user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_owned_admin_sees_all(monkeypatch) -> None:
    dep = SimpleNamespace(id="d1", owner_login="bob")
    monkeypatch.setattr(r.cdb, "get_deployment", AsyncMock(return_value=dep))
    user = SimpleNamespace(login="alice", roles=["admin"])
    assert await r._require_owned(None, "d1", user) is dep
