from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


def _write_recipe(
    base: Path,
    recipe_id: str,
    installs_after: list[str] | None = None,
    requires_secrets: list | None = None,
) -> None:
    d = base / recipe_id
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": recipe_id,
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

    _write_recipe(tmp_path, "base")
    _write_recipe(tmp_path, "node", installs_after=["base"])
    _write_recipe(tmp_path, "claude-code", installs_after=["node"])
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

    _write_recipe(tmp_path, "a", installs_after=["b"])
    _write_recipe(tmp_path, "b", installs_after=["a"])
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


def test_personal_overrides_shared(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    personal = tmp_path / "personal"
    # Partagée avec version 1.0.0
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
    # Personnelle avec version 2.0.0
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

    registry = RecipeRegistry(shared_dir=shared)
    shared_recipes = registry.load_shared()
    personal_recipes = registry.load_dir(personal)
    available = {**shared_recipes, **personal_recipes}
    assert len(available) == 1
    assert available["my-recipe"].version == "2.0.0"  # la version personnelle a gagné
