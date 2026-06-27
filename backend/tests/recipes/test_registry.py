from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import yaml

# GUIDs stables pour les recipes de test
_KEY_BASE = "aaaaaaaa-0000-0000-0000-000000000001"
_KEY_NODE = "aaaaaaaa-0000-0000-0000-000000000002"
_KEY_CLAUDE = "aaaaaaaa-0000-0000-0000-000000000003"
_KEY_A = "aaaaaaaa-0000-0000-0000-000000000004"
_KEY_B = "aaaaaaaa-0000-0000-0000-000000000005"


def _write_recipe(
    base: Path,
    recipe_id: str,
    key: str | None = None,
    installs_after: list[str] | None = None,
    requires_secrets: list | None = None,
) -> None:
    d = base / recipe_id
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": recipe_id,
        "key": key or str(uuid.uuid4()),
        "version": "1.0.0",
        "description": f"Recipe {recipe_id}",
        "installs_after": installs_after or [],
        "requires_secrets": requires_secrets or [],
    }
    (d / "recipe.meta.yaml").write_text(yaml.dump(meta), encoding="utf-8")
    (d / "devcontainer-feature.json").write_text(
        json.dumps({"id": recipe_id, "version": "1.0.0"}), encoding="utf-8"
    )
    (d / "install.sh").write_text("#!/usr/bin/env bash\necho installed\n", encoding="utf-8")


def test_load_dir_nonexistent_returns_empty(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    registry = RecipeRegistry()
    assert registry.load_dir(tmp_path / "nonexistent") == {}


def test_load_dir_loads_recipes(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    _write_recipe(tmp_path, "claude-code")
    _write_recipe(tmp_path, "aider")
    registry = RecipeRegistry()
    result = registry.load_dir(tmp_path)
    assert set(result.keys()) == {"claude-code", "aider"}


def test_load_dir_ignores_dir_without_meta(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    (tmp_path / "not-a-recipe").mkdir()
    registry = RecipeRegistry()
    result = registry.load_dir(tmp_path)
    assert result == {}


def test_load_shared_builtin_overridden_by_shared(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    shared = tmp_path / "shared"
    _write_recipe(builtin, "claude-code")
    _write_recipe(shared, "claude-code")
    from portal.recipes.registry import RecipeRegistry

    registry = RecipeRegistry(builtin_dir=builtin, shared_dir=shared)
    result = registry.load_shared()
    assert len(result) == 1
    assert "claude-code" in result


def test_resolve_order_respects_installs_after(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    _write_recipe(tmp_path, "base", key=_KEY_BASE)
    _write_recipe(tmp_path, "node", key=_KEY_NODE, installs_after=[_KEY_BASE])
    _write_recipe(tmp_path, "claude-code", key=_KEY_CLAUDE, installs_after=[_KEY_NODE])
    registry = RecipeRegistry()
    available = registry.load_dir(tmp_path)
    order = registry.resolve_order(["claude-code", "node", "base"], available)
    ids = [r.id for r in order]
    assert ids.index("base") < ids.index("node") < ids.index("claude-code")


def test_resolve_order_unknown_recipe_raises(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeNotFoundError, RecipeRegistry

    registry = RecipeRegistry()
    with pytest.raises(RecipeNotFoundError, match="unknown-recipe"):
        registry.resolve_order(["unknown-recipe"], {})


def test_resolve_order_duplicate_ids_raises(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    _write_recipe(tmp_path, "a")
    registry = RecipeRegistry()
    available = registry.load_dir(tmp_path)
    with pytest.raises(ValueError, match="doublons"):
        registry.resolve_order(["a", "a"], available)


def test_resolve_order_cycle_raises(tmp_path: Path) -> None:
    from portal.recipes.registry import CycleError, RecipeRegistry

    _write_recipe(tmp_path, "a", key=_KEY_A, installs_after=[_KEY_B])
    _write_recipe(tmp_path, "b", key=_KEY_B, installs_after=[_KEY_A])
    registry = RecipeRegistry()
    available = registry.load_dir(tmp_path)
    with pytest.raises(CycleError):
        registry.resolve_order(["a", "b"], available)


def test_resolve_order_no_deps_preserves_count(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    _write_recipe(tmp_path, "a")
    _write_recipe(tmp_path, "b")
    registry = RecipeRegistry()
    available = registry.load_dir(tmp_path)
    order = registry.resolve_order(["a", "b"], available)
    assert len(order) == 2


def test_expand_with_deps_adds_missing_dep(tmp_path: Path) -> None:
    """claude-code dépend de nodejs — nodejs doit être auto-ajouté."""
    from portal.recipes.registry import RecipeRegistry

    _write_recipe(tmp_path, "nodejs", key=_KEY_NODE)
    _write_recipe(tmp_path, "claude-code", key=_KEY_CLAUDE, installs_after=[_KEY_NODE])
    registry = RecipeRegistry()
    available = registry.load_dir(tmp_path)
    expanded = registry.expand_with_deps(["claude-code"], available)
    assert "nodejs" in expanded
    assert expanded.index("nodejs") < expanded.index("claude-code")


def test_expand_with_deps_no_duplicate_when_dep_already_selected(tmp_path: Path) -> None:
    """Si nodejs est déjà sélectionné + requis par claude-code, pas de doublon."""
    from portal.recipes.registry import RecipeRegistry

    _write_recipe(tmp_path, "nodejs", key=_KEY_NODE)
    _write_recipe(tmp_path, "claude-code", key=_KEY_CLAUDE, installs_after=[_KEY_NODE])
    registry = RecipeRegistry()
    available = registry.load_dir(tmp_path)
    expanded = registry.expand_with_deps(["nodejs", "claude-code"], available)
    assert expanded.count("nodejs") == 1
    assert expanded.index("nodejs") < expanded.index("claude-code")


def test_expand_with_deps_transitive(tmp_path: Path) -> None:
    """base → node → claude : sélectionner claude auto-inclut node et base."""
    from portal.recipes.registry import RecipeRegistry

    _write_recipe(tmp_path, "base", key=_KEY_BASE)
    _write_recipe(tmp_path, "node", key=_KEY_NODE, installs_after=[_KEY_BASE])
    _write_recipe(tmp_path, "claude-code", key=_KEY_CLAUDE, installs_after=[_KEY_NODE])
    registry = RecipeRegistry()
    available = registry.load_dir(tmp_path)
    expanded = registry.expand_with_deps(["claude-code"], available)
    assert set(expanded) == {"base", "node", "claude-code"}
    assert expanded.index("base") < expanded.index("node") < expanded.index("claude-code")


def test_expand_with_deps_unknown_dep_guid_raises(tmp_path: Path) -> None:
    """GUID de dépendance introuvable → DependencyNotFoundError."""
    from portal.recipes.registry import DependencyNotFoundError, RecipeRegistry

    ghost_key = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    _write_recipe(tmp_path, "claude-code", key=_KEY_CLAUDE, installs_after=[ghost_key])
    registry = RecipeRegistry()
    available = registry.load_dir(tmp_path)
    with pytest.raises(DependencyNotFoundError, match=ghost_key):
        registry.expand_with_deps(["claude-code"], available)


def _write_start_recipe(base: Path, recipe_id: str) -> None:
    """Écrit une recette de type start valide."""
    d = base / recipe_id
    d.mkdir(parents=True, exist_ok=True)
    meta = {"id": recipe_id, "version": "1.0.0", "description": "start recipe", "type": "start"}
    (d / "recipe.meta.yaml").write_text(yaml.dump(meta), encoding="utf-8")
    (d / "start.sh").write_text("#!/usr/bin/env bash\nexec claude --rc\n", encoding="utf-8")


def test_load_dir_accepts_valid_start_recipe(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    _write_start_recipe(tmp_path, "claude-rc")
    registry = RecipeRegistry()
    result = registry.load_dir(tmp_path)
    assert "claude-rc" in result
    assert result["claude-rc"].type == "start"


def test_load_dir_rejects_start_recipe_without_start_sh(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    d = tmp_path / "bad-start"
    d.mkdir()
    (d / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "bad-start", "type": "start"}), encoding="utf-8"
    )
    registry = RecipeRegistry()
    result = registry.load_dir(tmp_path)
    assert "bad-start" not in result


def test_load_dir_rejects_start_recipe_with_feature_json(tmp_path: Path) -> None:
    import json as _json

    from portal.recipes.registry import RecipeRegistry

    d = tmp_path / "bad-start2"
    d.mkdir()
    (d / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "bad-start2", "type": "start"}), encoding="utf-8"
    )
    (d / "start.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (d / "devcontainer-feature.json").write_text(
        _json.dumps({"id": "bad-start2"}), encoding="utf-8"
    )
    registry = RecipeRegistry()
    result = registry.load_dir(tmp_path)
    assert "bad-start2" not in result


def test_filter_by_type_returns_only_matching(tmp_path: Path) -> None:
    from portal.recipes.registry import RecipeRegistry

    _write_recipe(tmp_path, "my-install")
    _write_start_recipe(tmp_path, "my-start")
    registry = RecipeRegistry()
    all_recipes = registry.load_dir(tmp_path)
    starts = RecipeRegistry.filter_by_type(all_recipes, "start")
    installs = RecipeRegistry.filter_by_type(all_recipes, "install")
    assert set(starts.keys()) == {"my-start"}
    assert set(installs.keys()) == {"my-install"}


def test_personal_overrides_shared(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    personal = tmp_path / "personal"
    d_shared = shared / "my-recipe"
    d_shared.mkdir(parents=True)
    (d_shared / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "my-recipe", "version": "1.0.0", "description": "shared"}),
        encoding="utf-8",
    )
    (d_shared / "devcontainer-feature.json").write_text(
        json.dumps({"id": "my-recipe", "version": "1.0.0"}), encoding="utf-8"
    )
    (d_shared / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    d_personal = personal / "my-recipe"
    d_personal.mkdir(parents=True)
    (d_personal / "recipe.meta.yaml").write_text(
        yaml.dump({"id": "my-recipe", "version": "2.0.0", "description": "personal"}),
        encoding="utf-8",
    )
    (d_personal / "devcontainer-feature.json").write_text(
        json.dumps({"id": "my-recipe", "version": "2.0.0"}), encoding="utf-8"
    )
    (d_personal / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    from portal.recipes.registry import RecipeRegistry

    registry = RecipeRegistry(builtin_dir=None, shared_dir=shared)
    shared_recipes = registry.load_shared()
    personal_recipes = registry.load_dir(personal)
    available = {**shared_recipes, **personal_recipes}
    assert len(available) == 1
    assert available["my-recipe"].version == "2.0.0"
