"""Tests route auto-start + annotation de list_templates (purs, sans TestClient)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from portal.compose.models import ComposeAutoStart, ComposeParam, ComposeTemplate
from portal.routes import compose as r
from portal.schemas.compose import AutoStartUpdateBody

_USER = SimpleNamespace(login="alice", roles=["dev"])


def _tpl(**overrides: object) -> ComposeTemplate:
    base = dict(id="alloy-collector", name="Alloy", version="1", compose_content="services: {}")
    base.update(overrides)
    return ComposeTemplate(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_set_auto_start_enables(monkeypatch) -> None:
    monkeypatch.setattr(r.cdb, "get_template", AsyncMock(return_value=_tpl()))
    monkeypatch.setattr(r.cdb, "upsert_auto_start", AsyncMock())

    body = AutoStartUpdateBody(enabled=True, env_values={})
    result = await r.set_auto_start("alloy-collector", body, _USER, None)

    assert result == {"template_id": "alloy-collector", "enabled": True}
    r.cdb.upsert_auto_start.assert_awaited_once_with(None, "alice", "alloy-collector", {})


@pytest.mark.asyncio
async def test_set_auto_start_disables(monkeypatch) -> None:
    monkeypatch.setattr(r.cdb, "get_template", AsyncMock(return_value=_tpl()))
    monkeypatch.setattr(r.cdb, "delete_auto_start", AsyncMock())

    body = AutoStartUpdateBody(enabled=False)
    result = await r.set_auto_start("alloy-collector", body, _USER, None)

    assert result == {"template_id": "alloy-collector", "enabled": False}
    r.cdb.delete_auto_start.assert_awaited_once_with(None, "alice", "alloy-collector")


@pytest.mark.asyncio
async def test_set_auto_start_unknown_template_404(monkeypatch) -> None:
    monkeypatch.setattr(r.cdb, "get_template", AsyncMock(return_value=None))

    with pytest.raises(r.HTTPException) as exc:
        await r.set_auto_start("ghost", AutoStartUpdateBody(enabled=True), _USER, None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_set_auto_start_missing_required_param_422(monkeypatch) -> None:
    tpl = _tpl(parameters=[ComposeParam(key="PORT", label="Port", type="port", required=True)])
    monkeypatch.setattr(r.cdb, "get_template", AsyncMock(return_value=tpl))
    monkeypatch.setattr(r.cdb, "upsert_auto_start", AsyncMock())

    with pytest.raises(r.HTTPException) as exc:
        await r.set_auto_start("alloy-collector", AutoStartUpdateBody(enabled=True), _USER, None)
    assert exc.value.status_code == 422
    r.cdb.upsert_auto_start.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_templates_annotates_auto_start(monkeypatch) -> None:
    monkeypatch.setattr(r.cdb, "list_templates", AsyncMock(return_value=[_tpl(), _tpl(id="other")]))
    monkeypatch.setattr(
        r.cdb,
        "list_auto_start_for_user",
        AsyncMock(return_value=[ComposeAutoStart(id=1, owner_login="alice", template_id="other")]),
    )

    result = await r.list_templates(_USER, None, tag=None)

    by_id = {t["id"]: t["auto_start"] for t in result}
    assert by_id == {"alloy-collector": False, "other": True}
