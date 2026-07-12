# backend/tests/recipes/test_init_ops.py
"""Tests des opérations pures initialize (appliquées côté portail)."""

from __future__ import annotations

import pytest

from portal.recipes import init_ops as ops

# ── split_node ────────────────────────────────────────────────────────────────


def test_split_node() -> None:
    assert ops.split_node("$.a.b.c") == ["a", "b", "c"]


def test_split_node_invalid_raises() -> None:
    with pytest.raises(ValueError):
        ops.split_node("a.b")


# ── apply_replace ─────────────────────────────────────────────────────────────


def test_replace_creates_deep_node() -> None:
    root: dict = {}
    ops.apply_replace(root, "$.a.b.c", 42)
    assert root == {"a": {"b": {"c": 42}}}


def test_replace_preserves_siblings() -> None:
    root = {"keep": 1, "permissions": {"old": True}}
    ops.apply_replace(root, "$.permissions", {"new": True})
    assert root == {"keep": 1, "permissions": {"new": True}}


def test_replace_overwrites_non_dict_intermediate() -> None:
    root = {"a": "scalaire"}
    ops.apply_replace(root, "$.a.b", 1)
    assert root == {"a": {"b": 1}}


# ── apply_remove ──────────────────────────────────────────────────────────────


def test_remove_existing_node() -> None:
    root = {"a": {"b": 1, "c": 2}}
    ops.apply_remove(root, "$.a.b")
    assert root == {"a": {"c": 2}}


def test_remove_absent_node_is_noop() -> None:
    root = {"a": 1}
    ops.apply_remove(root, "$.x.y")
    assert root == {"a": 1}


# ── sentinel_location ─────────────────────────────────────────────────────────


def _spec(**kw) -> dict:
    base = {"recipe_id": "demo", "version": "1.0.0", "copy": [], "transform": []}
    base.update(kw)
    return base


def test_sentinel_prefers_transform_parent() -> None:
    spec = _spec(
        copy=[{"source": "files/x", "target": "/vol/data"}],
        transform=[
            {"op": "replace", "target": {"file": "/vol/.claude/settings.json", "node": "$.k"}}
        ],
    )
    base, rel = ops.sentinel_location(spec)
    assert base == "/vol/.claude"
    assert rel == ".portal/demo@1.0.0"


def test_sentinel_falls_back_to_copy_target_dir() -> None:
    spec = _spec(copy=[{"source": "files/x", "target": "/vol/.claude"}])
    base, rel = ops.sentinel_location(spec)
    assert base == "/vol/.claude"
    assert rel == ".portal/demo@1.0.0"


def test_sentinel_copy_file_source_uses_parent() -> None:
    spec = _spec(copy=[{"source": "files/x.json", "target": "/vol/.claude/x.json"}])
    base, _rel = ops.sentinel_location(spec, first_copy_source_is_file=True)
    assert base == "/vol/.claude"


def test_sentinel_no_ops_falls_back_to_home() -> None:
    base, rel = ops.sentinel_location(_spec())
    assert base is None
    assert rel == ".portal/demo@1.0.0"
