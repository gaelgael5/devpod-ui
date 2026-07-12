"""Endpoints préférences utilisateur — validation valeur typée + garde clé."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import portal.routes.preferences as rt
from portal.routes.preferences import PreferenceValueBody

USER = type("U", (), {"login": "alice"})()
CONN = object()


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    m = AsyncMock()
    monkeypatch.setattr(rt, "list_preferences", m.list_preferences)
    monkeypatch.setattr(rt, "upsert_preference", m.upsert_preference)
    monkeypatch.setattr(rt, "ensure_user_db", m.ensure_user_db)
    return m


def test_body_exactly_one_value() -> None:
    assert PreferenceValueBody.model_validate({"bool": True}).value() is True
    assert PreferenceValueBody.model_validate({"int": 5}).value() == 5
    assert PreferenceValueBody.model_validate({"string": "x"}).value() == "x"
    # false/0 restent une valeur valide (un seul champ renseigné).
    assert PreferenceValueBody.model_validate({"bool": False}).value() is False
    assert PreferenceValueBody.model_validate({"int": 0}).value() == 0


def test_body_rejects_zero_or_two_values() -> None:
    with pytest.raises(ValidationError):
        PreferenceValueBody.model_validate({})
    with pytest.raises(ValidationError):
        PreferenceValueBody.model_validate({"bool": True, "int": 1})


@pytest.mark.asyncio
async def test_put_persists_typed_value(db: AsyncMock) -> None:
    body = PreferenceValueBody.model_validate({"bool": True})
    await rt.put_preference(
        key="workspaces.group.3.collapse", body=body, user=USER, conn=CONN
    )
    db.ensure_user_db.assert_awaited_once_with("alice", CONN)
    db.upsert_preference.assert_awaited_once_with(
        "alice", "workspaces.group.3.collapse", True, CONN
    )


@pytest.mark.asyncio
async def test_put_rejects_invalid_key(db: AsyncMock) -> None:
    body = PreferenceValueBody.model_validate({"bool": True})
    with pytest.raises(HTTPException) as exc:
        await rt.put_preference(key="bad key!", body=body, user=USER, conn=CONN)
    assert exc.value.status_code == 422
    db.upsert_preference.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_returns_map(db: AsyncMock) -> None:
    db.list_preferences.return_value = {"workspaces.group.3.collapse": True}
    out = await rt.get_preferences(user=USER, conn=CONN)
    assert out == {"workspaces.group.3.collapse": True}
    db.list_preferences.assert_awaited_once_with("alice", CONN)
