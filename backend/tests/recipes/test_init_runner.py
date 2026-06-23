# backend/tests/recipes/test_init_runner.py
"""Tests du moteur d'initialisation (exécuté tel quel dans le conteneur)."""

from __future__ import annotations

import json
from pathlib import Path

from portal.recipes import _init_runner as runner


def _spec(**kw):
    base = {"recipe_id": "demo", "version": "1.0.0", "copy": [], "transform": []}
    base.update(kw)
    return base


# ── transform: replace ────────────────────────────────────────────────────────


def test_replace_creates_file_and_deep_node(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    spec = _spec(
        transform=[
            {
                "op": "replace",
                "target": {"file": str(target), "node": "$.permissions"},
                "value": {"allow": [], "defaultMode": "bypassPermissions"},
            }
        ]
    )
    res = runner.run(spec, src_root=None, force=False)
    assert res["applied"] is True
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["permissions"] == {"allow": [], "defaultMode": "bypassPermissions"}


def test_replace_preserves_siblings(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"keep": 1, "permissions": {"old": True}}), encoding="utf-8")
    spec = _spec(
        transform=[
            {
                "op": "replace",
                "target": {"file": str(target), "node": "$.permissions"},
                "value": {"new": True},
            }
        ]
    )
    runner.run(spec, src_root=None, force=False)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["keep"] == 1
    assert data["permissions"] == {"new": True}


def test_replace_nested_path(tmp_path: Path) -> None:
    target = tmp_path / "c.json"
    spec = _spec(
        transform=[
            {
                "op": "replace",
                "target": {"file": str(target), "node": "$.a.b.c"},
                "value": 42,
            }
        ]
    )
    runner.run(spec, src_root=None, force=False)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {"a": {"b": {"c": 42}}}


# ── transform: remove ─────────────────────────────────────────────────────────


def test_remove_existing_node(tmp_path: Path) -> None:
    target = tmp_path / "s.json"
    target.write_text(json.dumps({"a": {"b": 1, "c": 2}}), encoding="utf-8")
    spec = _spec(transform=[{"op": "remove", "target": {"file": str(target), "node": "$.a.b"}}])
    runner.run(spec, src_root=None, force=False)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {"a": {"c": 2}}


def test_remove_absent_node_is_noop(tmp_path: Path) -> None:
    target = tmp_path / "s.json"
    target.write_text(json.dumps({"a": 1}), encoding="utf-8")
    spec = _spec(transform=[{"op": "remove", "target": {"file": str(target), "node": "$.x.y"}}])
    res = runner.run(spec, src_root=None, force=False)
    assert res["applied"] is True
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


def test_remove_absent_file_is_noop(tmp_path: Path) -> None:
    target = tmp_path / "missing.json"
    spec = _spec(transform=[{"op": "remove", "target": {"file": str(target), "node": "$.x"}}])
    res = runner.run(spec, src_root=None, force=False)
    assert res["applied"] is True
    assert not target.exists()


# ── copy ──────────────────────────────────────────────────────────────────────


def test_copy_directory_into_target(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    (src_root / "files" / "claude").mkdir(parents=True)
    (src_root / "files" / "claude" / "agents.md").write_text("hello", encoding="utf-8")
    target = tmp_path / "out" / ".claude"
    spec = _spec(copy=[{"source": "files/claude", "target": str(target)}])
    runner.run(spec, src_root=str(src_root), force=False)
    assert (target / "agents.md").read_text(encoding="utf-8") == "hello"


def test_copy_single_file(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    (src_root / "files").mkdir(parents=True)
    (src_root / "files" / "x.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "out" / "x.json"
    spec = _spec(copy=[{"source": "files/x.json", "target": str(target)}])
    runner.run(spec, src_root=str(src_root), force=False)
    assert target.read_text(encoding="utf-8") == "{}"


# ── sentinelle ────────────────────────────────────────────────────────────────


def test_sentinel_blocks_second_run(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "settings.json"
    spec = _spec(
        transform=[{"op": "replace", "target": {"file": str(target), "node": "$.k"}, "value": 1}]
    )
    first = runner.run(spec, src_root=None, force=False)
    assert first["applied"] is True and first["already_applied"] is False

    # La sentinelle est posée dans <dir cible>/.portal/<id>@<version>
    sentinel = tmp_path / ".claude" / ".portal" / "demo@1.0.0"
    assert sentinel.exists()

    # Deuxième passage : court-circuité, valeur non réécrite même si on la modifie
    target.write_text(json.dumps({"k": 999}), encoding="utf-8")
    second = runner.run(spec, src_root=None, force=False)
    assert second["already_applied"] is True
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 999}


def test_force_ignores_sentinel(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "settings.json"
    spec = _spec(
        transform=[{"op": "replace", "target": {"file": str(target), "node": "$.k"}, "value": 1}]
    )
    runner.run(spec, src_root=None, force=False)
    target.write_text(json.dumps({"k": 999}), encoding="utf-8")
    res = runner.run(spec, src_root=None, force=True)
    assert res["applied"] is True
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 1}


def test_sentinel_path_prefers_transform_parent(tmp_path: Path) -> None:
    spec = _spec(
        copy=[{"source": "files/x", "target": "/vol/data"}],
        transform=[
            {
                "op": "replace",
                "target": {"file": "/vol/.claude/settings.json", "node": "$.k"},
                "value": 1,
            }
        ],
    )
    p = runner.sentinel_path(spec)
    assert p == Path("/vol/.claude/.portal/demo@1.0.0")


def test_sentinel_path_falls_back_to_copy_target(tmp_path: Path) -> None:
    spec = _spec(copy=[{"source": "files/x", "target": "/vol/.claude"}])
    p = runner.sentinel_path(spec)
    assert p == Path("/vol/.claude/.portal/demo@1.0.0")
