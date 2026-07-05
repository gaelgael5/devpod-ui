"""Règles docflow : amorçage workspace + blocs planner/wiki, idempotence."""

from __future__ import annotations

from typing import Any

from portal.automation.docflow_rules import DOCFLOW_BOOTSTRAP_RULES
from portal.automation.engine import run_rules
from portal.events.models import AppEvent


class _StubCaller:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, owner: str, namespace: str, tool: str, args: dict[str, Any]) -> Any:
        assert namespace == "docflow"
        self.calls.append((tool, args))
        return self.responses[tool]


def _event(event_type: str = "workspace.created") -> AppEvent:
    return AppEvent(type=event_type, actor="alice", workspace="mon-projet")


async def test_amorcage_complet_sur_workspace_vierge() -> None:
    caller = _StubCaller(
        {
            "list_workspaces": [{"slug": "autre", "label": "Autre"}],
            "create_workspace": {"slug": "mon-projet"},
            "list_documents": [],
            "create_block": {"slug": "ok"},
        }
    )
    outcomes = await run_rules(DOCFLOW_BOOTSTRAP_RULES, _event(), caller)
    assert [o["matched"] for o in outcomes] == [True, True, True]

    created = [args for tool, args in caller.calls if tool == "create_workspace"]
    assert created == [{"slug": "mon-projet", "label": "mon-projet"}]

    blocks = [args for tool, args in caller.calls if tool == "create_block"]
    assert [b["functional_type_slug"] for b in blocks] == ["planner", "wiki"]
    assert all(b["workspace_slug"] == "mon-projet" for b in blocks)


async def test_idempotence_quand_tout_existe() -> None:
    caller = _StubCaller(
        {
            "list_workspaces": [{"slug": "mon-projet", "label": "Mon Projet"}],
            "list_documents": [
                {"id": "1", "title": "Plan", "functional_type_slug": "planner"},
                {"id": "2", "title": "Wiki", "functional_type_slug": "wiki"},
            ],
        }
    )
    outcomes = await run_rules(DOCFLOW_BOOTSTRAP_RULES, _event(), caller)
    assert [o["matched"] for o in outcomes] == [False, False, False]
    tools = {tool for tool, _ in caller.calls}
    assert tools == {"list_workspaces", "list_documents"}


async def test_declenche_aussi_sur_restart_mais_pas_sur_delete() -> None:
    caller = _StubCaller(
        {
            "list_workspaces": [{"slug": "mon-projet"}],
            "list_documents": [
                {"functional_type_slug": "planner"},
                {"functional_type_slug": "wiki"},
            ],
        }
    )
    assert len(await run_rules(DOCFLOW_BOOTSTRAP_RULES, _event("workspace.restarted"), caller)) == 3
    assert await run_rules(DOCFLOW_BOOTSTRAP_RULES, _event("workspace.deleted"), caller) == []


async def test_document_sans_type_ne_compte_pas() -> None:
    """Un document au functional_type_slug null n'est ni planner ni wiki."""
    caller = _StubCaller(
        {
            "list_workspaces": [{"slug": "mon-projet"}],
            "list_documents": [{"id": "1", "title": "Brouillon", "functional_type_slug": None}],
            "create_block": {"slug": "ok"},
        }
    )
    outcomes = await run_rules(DOCFLOW_BOOTSTRAP_RULES, _event(), caller)
    assert [o["matched"] for o in outcomes] == [False, True, True]
