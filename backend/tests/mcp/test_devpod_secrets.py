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


@pytest.mark.asyncio
async def test_secrets_bind_sets_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = SimpleNamespace(name="dev", env={})
    def model_copy(update):
        spec.env = {**spec.env, **update.get("env", {})}
        return spec
    spec.model_copy = model_copy
    cfg = SimpleNamespace(workspaces=[spec])
    saved = {}
    monkeypatch.setattr(devpod_tools, "load_user", AsyncMock(return_value=cfg))
    monkeypatch.setattr(
        devpod_tools, "save_user",
        AsyncMock(side_effect=lambda login, config: saved.update(cfg=config))
    )
    res = await devpod_tools._workspace_secrets_bind(
        None,
        {"workspace": "dev", "reference": "${vault://b/n}", "target": "API_KEY"},
        "alice"
    )
    assert res == {"target": "API_KEY", "bound": True}
    assert spec.env["API_KEY"] == "${vault://b/n}"


@pytest.mark.asyncio
async def test_secrets_bind_rejects_non_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(workspaces=[SimpleNamespace(name="dev", env={})])
    monkeypatch.setattr(devpod_tools, "load_user", AsyncMock(return_value=cfg))
    with pytest.raises(devpod_tools.DevpodToolError):
        await devpod_tools._workspace_secrets_bind(
            None, {"workspace": "dev", "reference": "plaintext", "target": "API_KEY"}, "alice"
        )
