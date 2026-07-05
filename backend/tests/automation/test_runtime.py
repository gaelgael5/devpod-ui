"""Runtime des règles utilisateur : conversion ligne DB → règle moteur."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from portal.automation.runtime import rule_row_to_engine


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "r1",
        "owner_login": "alice",
        "name": "docflow workspace",
        "enabled": True,
        "event_type": "workspace.created",
        "probe_service_id": "svc-1",
        "probe_tool": "docflow__list_workspaces",
        "probe_args": {},
        "condition_path": "slug",
        "condition_operator": "not_contains",
        "condition_value": "{workspace}",
        "action_service_id": "svc-1",
        "action_tool": "docflow__create_workspace",
        "action_args": {"slug": "{workspace}", "label": "{workspace}"},
        "created_at": None,
        "updated_at": None,
    }
    base.update(overrides)
    return base


def test_conversion_complete() -> None:
    rule = rule_row_to_engine(_row())
    assert rule.name == "docflow workspace"
    assert rule.events == ("workspace.created",)
    assert rule.probe.service_id == "svc-1"
    assert rule.probe.tool == "docflow__list_workspaces"
    assert rule.condition.operator == "not_contains"
    assert rule.action.args == {"slug": "{workspace}", "label": "{workspace}"}


def test_service_supprime_donne_service_id_none() -> None:
    rule = rule_row_to_engine(_row(probe_service_id=None))
    assert rule.probe.service_id is None


def test_event_type_inconnu_rejete() -> None:
    with pytest.raises(ValidationError):
        rule_row_to_engine(_row(event_type="workspace.exploded"))


def test_operateur_inconnu_rejete() -> None:
    with pytest.raises(ValidationError):
        rule_row_to_engine(_row(condition_operator="regex"))
