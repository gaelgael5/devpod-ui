"""Règles d'amorçage docflow : tout workspace devpod a son pendant docflow.

À la création (ou au redémarrage — filet de rattrapage) d'un workspace devpod :
1. le workspace docflow du même slug existe, sinon création ;
2. un bloc de type `planner` y existe, sinon création ;
3. un bloc de type `wiki` y existe, sinon création.

Les règles sont des données : les slugs de types/templates docflow se corrigent
ici sans toucher au moteur. La sonde des blocs s'appuie sur list_documents
(functional_type_slug) — docflow n'expose pas de list_blocks à ce jour.
"""

from __future__ import annotations

from .models import Condition, PrimitiveCall, Rule

_EVENTS = ("workspace.created", "workspace.restarted")
_NS = "docflow"


def _block_rule(type_slug: str, label: str) -> Rule:
    return Rule(
        name=f"docflow-{type_slug}-block-exists",
        events=_EVENTS,
        probe=PrimitiveCall(
            namespace=_NS, tool="list_documents", args={"workspace_slug": "{workspace}"}
        ),
        condition=Condition(path="functional_type_slug", operator="not_contains", value=type_slug),
        action=PrimitiveCall(
            namespace=_NS,
            tool="create_block",
            args={
                "workspace_slug": "{workspace}",
                "slug": type_slug,
                "label": label,
                "functional_type_slug": type_slug,
                "template_slug": type_slug,
            },
        ),
    )


DOCFLOW_BOOTSTRAP_RULES: tuple[Rule, ...] = (
    Rule(
        name="docflow-workspace-exists",
        events=_EVENTS,
        probe=PrimitiveCall(namespace=_NS, tool="list_workspaces", args={}),
        condition=Condition(path="slug", operator="not_contains", value="{workspace}"),
        action=PrimitiveCall(
            namespace=_NS,
            tool="create_workspace",
            args={"slug": "{workspace}", "label": "{workspace}"},
        ),
    ),
    _block_rule("planner", "Planner"),
    _block_rule("wiki", "Wiki"),
)
