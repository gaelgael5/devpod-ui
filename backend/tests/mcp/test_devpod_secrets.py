from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.mcp import devpod_tools


@pytest.mark.asyncio
async def test_secrets_list_only_references(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = SimpleNamespace(name="dev", env={
        "API_KEY": "${vault://bloc/api}",
        "DB_URL": "${env://DATABASE_URL}",
        "PLAIN": "literal",
    })
    cfg = SimpleNamespace(workspaces=[spec])
    monkeypatch.setattr(devpod_tools, "load_user_db", AsyncMock(return_value=cfg))
    res = await devpod_tools._workspace_secrets_list(None, {"workspace": "dev"}, "alice")
    refs = {r["target"]: r["reference"] for r in res["references"]}
    assert refs == {"API_KEY": "${vault://bloc/api}", "DB_URL": "${env://DATABASE_URL}"}
    assert "PLAIN" not in refs
