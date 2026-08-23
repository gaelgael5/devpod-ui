"""Schéma de l'arbre de règle : récursion, union feuille/groupe, invariants."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.automations.tree import EMPTY_TREE, RuleTree, iter_calls


def _leaf(**over: object) -> dict[str, object]:
    return {
        "url": "https://api.example.org/check",
        "jsonpath": "$.ok",
        "operator": "exists",
        **over,
    }


def _call(name: str) -> dict[str, object]:
    return {"name": name, "url": "https://api.example.org/do", "http_method": "POST"}


def test_empty_tree_valid() -> None:
    tree = RuleTree.model_validate(EMPTY_TREE)
    assert tree.version == 1 and tree.blocks == []


def test_recursive_blocks_and_nested_filters() -> None:
    tree = RuleTree.model_validate(
        {
            "version": 1,
            "blocks": [
                {
                    "label": "racine",
                    "filter": {
                        "op": "and",
                        "items": [
                            _leaf(),
                            {
                                "op": "or",
                                "items": [_leaf(operator="equals", expected="x"), _leaf()],
                            },
                        ],
                    },
                    "calls": [_call("createHost")],
                    "blocks": [
                        {"label": "enfant", "calls": [_call("share")], "blocks": []},
                    ],
                }
            ],
        }
    )
    root = tree.blocks[0]
    assert root.filter is not None and root.filter.op == "and"  # type: ignore[union-attr]
    assert [c.name for c in iter_calls(tree.blocks)] == ["createHost", "share"]


def test_duplicate_call_names_rejected() -> None:
    with pytest.raises(ValidationError, match="dupliqué"):
        RuleTree.model_validate(
            {
                "blocks": [
                    {"calls": [_call("a")], "blocks": [{"calls": [_call("a")]}]},
                ]
            }
        )


def test_call_name_must_be_template_root() -> None:
    for bad in ("a.b", "1abc", "", "é"):
        with pytest.raises(ValidationError):
            RuleTree.model_validate({"blocks": [{"calls": [_call(bad)]}]})


def test_unknown_operator_rejected() -> None:
    with pytest.raises(ValidationError, match="opérateur"):
        RuleTree.model_validate({"blocks": [{"filter": _leaf(operator="regex")}]})


def test_unknown_method_rejected() -> None:
    bad = _call("a")
    bad["http_method"] = "FETCH"
    with pytest.raises(ValidationError):
        RuleTree.model_validate({"blocks": [{"calls": [bad]}]})


def test_empty_group_rejected() -> None:
    with pytest.raises(ValidationError):
        RuleTree.model_validate({"blocks": [{"filter": {"op": "and", "items": []}}]})


def test_call_headers_value_xor_secret() -> None:
    call = dict(_call("a"))
    call["headers"] = [{"name": "Authorization", "value": "t", "secret_ref": "${system://k}"}]
    with pytest.raises(ValidationError, match="exclusifs"):
        RuleTree.model_validate({"blocks": [{"calls": [call]}]})


def test_call_headers_accepted_and_normalized() -> None:
    call = dict(_call("a"))
    call["headers"] = [
        {"name": "Authorization", "secret_ref": "${system://k}", "value_prefix": "Bearer "}
    ]
    tree = RuleTree.model_validate({"blocks": [{"calls": [call]}]})
    hdr = tree.blocks[0].calls[0].headers[0]
    assert hdr.enabled is True and hdr.value is None and hdr.value_prefix == "Bearer "


def test_leaf_and_group_union_unambiguous() -> None:
    # Un dict avec `op` + feuille mélangés ne doit matcher aucun des deux membres.
    with pytest.raises(ValidationError):
        RuleTree.model_validate({"blocks": [{"filter": {"op": "and", **_leaf()}}]})
