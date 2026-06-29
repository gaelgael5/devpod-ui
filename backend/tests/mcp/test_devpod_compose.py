"""Tests des outils MCP internes galerie compose (compose_tools.py)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.mcp.devpod_tools import compose_tools
from portal.mcp.devpod_tools.errors import DevpodToolError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tpl(tpl_id: str = "chromium") -> SimpleNamespace:
    return SimpleNamespace(
        id=tpl_id,
        name="Chromium",
        version="1",
        description="",
        tags=["browser"],
        compose_content=(
            "services:\n"
            "  browser:\n"
            "    image: chromium:1.0.0\n"
            "    ports:\n"
            "      - chromium>3000:3000\n"
        ),
        parameters=[],
        source="user",
        model_dump=lambda mode=None: {"id": tpl_id, "name": "Chromium"},
        model_copy=lambda update=None: _tpl(tpl_id),
    )


def _dep(dep_id: str = "dep1", owner: str = "alice") -> SimpleNamespace:
    return SimpleNamespace(
        id=dep_id,
        template_id="chromium",
        template_version="1",
        node_id="node1",
        owner_login=owner,
        host_ports=[3005],
        status="running",
        model_dump=lambda mode=None: {
            "id": dep_id, "node_id": "node1", "status": "running", "host_ports": [3005]
        },
    )


# ---------------------------------------------------------------------------
# compose_template_list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_template_list_returns_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "list_templates", AsyncMock(return_value=[_tpl()]))
    result = await compose_tools._compose_template_list(None, {}, "alice")
    assert isinstance(result, list)
    assert result[0]["id"] == "chromium"
    assert "compose_content" not in result[0]  # pas de YAML dans la liste


@pytest.mark.asyncio
async def test_template_list_with_tag_passes_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr(compose_tools.cdb, "list_templates", mock)
    await compose_tools._compose_template_list(None, {"tag": "browser"}, "alice")
    mock.assert_awaited_once_with(None, tag="browser")


# ---------------------------------------------------------------------------
# compose_template_get
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_template_get_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "get_template", AsyncMock(return_value=_tpl()))
    result = await compose_tools._compose_template_get(None, {"template_id": "chromium"}, "alice")
    assert result["id"] == "chromium"


@pytest.mark.asyncio
async def test_template_get_not_found_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "get_template", AsyncMock(return_value=None))
    with pytest.raises(DevpodToolError, match="inconnu"):
        await compose_tools._compose_template_get(None, {"template_id": "x"}, "alice")


# ---------------------------------------------------------------------------
# compose_template_create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_template_create_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "get_template", AsyncMock(return_value=None))
    monkeypatch.setattr(compose_tools.cdb, "create_template", AsyncMock())
    monkeypatch.setattr(
        compose_tools, "validate_template", lambda content, params: []
    )
    result = await compose_tools._compose_template_create(
        None,
        {"id": "my-svc", "name": "My Service",
         "compose_content": "services:\n  s:\n    image: x:1"},
        "admin",
    )
    assert result["created"] is True
    assert result["id"] == "my-svc"
    compose_tools.cdb.create_template.assert_awaited_once()


@pytest.mark.asyncio
async def test_template_create_duplicate_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "get_template", AsyncMock(return_value=_tpl()))
    with pytest.raises(DevpodToolError, match="existe déjà"):
        await compose_tools._compose_template_create(
            None,
            {"id": "chromium", "name": "X", "compose_content": "services:\n  s:\n    image: x:1"},
            "admin",
        )


@pytest.mark.asyncio
async def test_template_create_invalid_slug_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "get_template", AsyncMock(return_value=None))
    with pytest.raises(DevpodToolError):
        await compose_tools._compose_template_create(
            None,
            {"id": "INVALID SLUG!", "name": "X",
             "compose_content": "services:\n  s:\n    image: x:1"},
            "admin",
        )


@pytest.mark.asyncio
async def test_template_create_validation_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from portal.compose.validation import TemplateValidationError
    monkeypatch.setattr(compose_tools.cdb, "get_template", AsyncMock(return_value=None))
    monkeypatch.setattr(
        compose_tools, "validate_template",
        lambda c, p: (_ for _ in ()).throw(TemplateValidationError("port codé en dur")),
    )
    with pytest.raises(DevpodToolError, match="port"):
        await compose_tools._compose_template_create(
            None,
            {"id": "ok-slug", "name": "X",
             "compose_content": "services:\n  web:\n    image: x:1\n    ports: [\"3000:80\"]\n"},
            "admin",
        )


# ---------------------------------------------------------------------------
# compose_service_list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_list_returns_own_deployments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        compose_tools.cdb, "list_deployments",
        AsyncMock(return_value=[_dep("dep1", "alice"), _dep("dep2", "alice")])
    )
    result = await compose_tools._compose_service_list(None, {}, "alice")
    assert len(result) == 2
    assert result[0]["id"] == "dep1"


@pytest.mark.asyncio
async def test_service_list_filters_by_node(monkeypatch: pytest.MonkeyPatch) -> None:
    d1 = _dep("dep1")
    d2 = _dep("dep2")
    d2.node_id = "other-node"
    monkeypatch.setattr(compose_tools.cdb, "list_deployments", AsyncMock(return_value=[d1, d2]))
    result = await compose_tools._compose_service_list(None, {"node_id": "node1"}, "alice")
    assert len(result) == 1
    assert result[0]["id"] == "dep1"


# ---------------------------------------------------------------------------
# compose_service_start
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_start_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "get_template", AsyncMock(return_value=_tpl()))
    monkeypatch.setattr(compose_tools.cdb, "get_deployment", AsyncMock(return_value=None))
    user_ns = SimpleNamespace(secret_ns="ns")
    monkeypatch.setattr(compose_tools, "load_user", AsyncMock(return_value=user_ns))
    monkeypatch.setattr(compose_tools.csvc, "deploy", AsyncMock(return_value=_dep()))
    result = await compose_tools._compose_service_start(
        None, {"template_id": "chromium", "node_id": "node1", "name": "dep1"}, "alice"
    )
    assert result["id"] == "dep1"
    assert result["host_ports"] == [3005]


@pytest.mark.asyncio
async def test_service_start_unknown_template_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "get_template", AsyncMock(return_value=None))
    with pytest.raises(DevpodToolError, match="template inconnu"):
        await compose_tools._compose_service_start(
            None, {"template_id": "xx", "node_id": "n1", "name": "my-dep"}, "alice"
        )


@pytest.mark.asyncio
async def test_service_start_duplicate_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "get_template", AsyncMock(return_value=_tpl()))
    monkeypatch.setattr(compose_tools.cdb, "get_deployment", AsyncMock(return_value=_dep()))
    with pytest.raises(DevpodToolError, match="existe déjà"):
        await compose_tools._compose_service_start(
            None, {"template_id": "chromium", "node_id": "node1", "name": "dep1"}, "alice"
        )


# ---------------------------------------------------------------------------
# compose_service_stop / restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_stop_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "get_deployment", AsyncMock(return_value=_dep()))
    monkeypatch.setattr(compose_tools.csvc, "lifecycle", AsyncMock())
    result = await compose_tools._compose_service_stop(None, {"deployment_id": "dep1"}, "alice")
    assert result["action"] == "stop"
    compose_tools.csvc.lifecycle.assert_awaited_once_with(None, "dep1", "stop")


@pytest.mark.asyncio
async def test_service_stop_wrong_owner_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    dep_bob = _dep("dep1", "bob")
    monkeypatch.setattr(compose_tools.cdb, "get_deployment", AsyncMock(return_value=dep_bob))
    with pytest.raises(DevpodToolError, match="inconnu"):
        await compose_tools._compose_service_stop(None, {"deployment_id": "dep1"}, "alice")


@pytest.mark.asyncio
async def test_service_restart_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "get_deployment", AsyncMock(return_value=_dep()))
    monkeypatch.setattr(compose_tools.csvc, "lifecycle", AsyncMock())
    result = await compose_tools._compose_service_restart(None, {"deployment_id": "dep1"}, "alice")
    assert result["action"] == "restart"


# ---------------------------------------------------------------------------
# compose_service_down
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_down_requires_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(DevpodToolError, match="confirm"):
        await compose_tools._compose_service_down(
            None, {"deployment_id": "dep1", "confirm": False}, "alice"
        )


@pytest.mark.asyncio
async def test_service_down_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose_tools.cdb, "get_deployment", AsyncMock(return_value=_dep()))
    monkeypatch.setattr(compose_tools.csvc, "teardown", AsyncMock())
    result = await compose_tools._compose_service_down(
        None, {"deployment_id": "dep1", "confirm": True}, "alice"
    )
    assert result["torn_down"] is True
    compose_tools.csvc.teardown.assert_awaited_once_with(None, "dep1")


# ---------------------------------------------------------------------------
# Registre : les 11 outils sont dans COMPOSE_IMPLS et DEVPOD_PRIMITIVES
# ---------------------------------------------------------------------------

def test_compose_impls_all_registered() -> None:
    from portal.mcp.devpod_tools.compose_tools import COMPOSE_IMPLS
    from portal.mcp.devpod_tools.registry import DEVPOD_PRIMITIVES

    for name in COMPOSE_IMPLS:
        assert name in DEVPOD_PRIMITIVES, f"{name} manquant dans DEVPOD_PRIMITIVES"


def test_dispatch_table_contains_compose_tools() -> None:
    from portal.mcp.devpod_tools import _IMPLS
    from portal.mcp.devpod_tools.compose_tools import COMPOSE_IMPLS

    for name in COMPOSE_IMPLS:
        assert name in _IMPLS, f"{name} manquant dans _IMPLS"
