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


@pytest.mark.asyncio
async def test_create_deployment_rejects_foreign_env_key(monkeypatch) -> None:
    """Bug 002 : une clé env_values non déclarée par le template → 422, sans déploiement."""
    from portal.compose.models import ComposeParam, ComposeTemplate
    from portal.schemas.compose import DeploymentCreateBody

    tpl = ComposeTemplate(
        id="svc", name="Svc", version="1",
        compose_content="services:\n  s:\n    image: x:1",
        parameters=[ComposeParam(key="PORT", label="Port", type="port", required=False)],
        source="user",
    )
    monkeypatch.setattr(r.cdb, "get_template", AsyncMock(return_value=tpl))
    deploy_spy = AsyncMock()
    monkeypatch.setattr(r.csvc, "deploy", deploy_spy)

    body = DeploymentCreateBody(
        template_id="svc", node_id="n1", name="dep1",
        env_values={"PORT": "3000", "LEAK": "${env://PORTAL_VAULT_KEK}"},
    )
    user = SimpleNamespace(login="alice", roles=["dev"])
    with pytest.raises(r.HTTPException) as exc:
        await r.create_deployment(body, user, None)
    assert exc.value.status_code == 422
    assert "LEAK" in str(exc.value.detail)
    deploy_spy.assert_not_awaited()
