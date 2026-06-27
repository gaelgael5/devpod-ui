# backend/tests/recipes/test_devcontainer_gen.py
from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml


def _make_recipe_dir(recipes_root: Path, recipe_id: str) -> None:
    """Crée une Feature dir minimale dans recipes_root (équivalent /data/recipes/)."""
    d = recipes_root / recipe_id
    d.mkdir(parents=True)
    (d / "devcontainer-feature.json").write_text(
        json.dumps({"id": recipe_id, "version": "1.0.0"}), encoding="utf-8"
    )
    (d / "install.sh").write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
    (d / "recipe.meta.yaml").write_text(
        yaml.dump({"id": recipe_id, "version": "1.0.0", "description": f"Recipe {recipe_id}"}),
        encoding="utf-8",
    )


def test_write_devcontainer_no_recipes(tmp_data_root, global_cfg, fake_devpod_bin) -> None:
    """Sans recettes, devcontainer.json contient image de base et pas de features."""
    import asyncio

    from portal.auth.router import provision_user
    from portal.devpod.service import DevPodService

    asyncio.run(provision_user(login="alice", sub="sub", data_root=tmp_data_root))
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    dc_path = svc._write_devcontainer("alice", "alice-myapp")
    try:
        content = json.loads(dc_path.read_text(encoding="utf-8"))
        assert "image" in content
        assert "features" not in content
        assert "remoteEnv" not in content
    finally:
        shutil.rmtree(dc_path.parent, ignore_errors=True)


def test_write_devcontainer_with_recipe_copies_feature_dir(
    tmp_data_root, global_cfg, fake_devpod_bin
) -> None:
    """Avec une recette, la Feature dir est copiée dans le tmpdir et référencée en chemin local."""
    import asyncio

    from portal.auth.router import provision_user
    from portal.devpod.service import DevPodService
    from portal.recipes.models import RecipeMeta

    asyncio.run(provision_user(login="alice", sub="sub", data_root=tmp_data_root))
    _make_recipe_dir(tmp_data_root / "recipes", "claude-code")
    recipe = RecipeMeta(id="claude-code")

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    dc_path = svc._write_devcontainer("alice", "alice-myapp", recipes=[recipe])
    try:
        content = json.loads(dc_path.read_text(encoding="utf-8"))
        assert "features" in content
        assert "./claude-code" in content["features"]
        assert (dc_path.parent / "claude-code" / "install.sh").exists()
    finally:
        shutil.rmtree(dc_path.parent, ignore_errors=True)


def test_write_devcontainer_secrets_in_remote_env_not_features(
    tmp_data_root, global_cfg, fake_devpod_bin
) -> None:
    """§D-21 : les secrets vont dans remoteEnv, PAS dans les options features."""
    import asyncio

    from portal.auth.router import provision_user
    from portal.devpod.service import DevPodService
    from portal.recipes.models import RecipeMeta

    asyncio.run(provision_user(login="alice", sub="sub", data_root=tmp_data_root))
    _make_recipe_dir(tmp_data_root / "recipes", "aider")
    recipe = RecipeMeta(id="aider")
    feature_env = {"ANTHROPIC_API_KEY": "sk-secret-value"}

    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    dc_path = svc._write_devcontainer(
        "alice", "alice-myapp", recipes=[recipe], feature_env=feature_env
    )
    try:
        content = json.loads(dc_path.read_text(encoding="utf-8"))
        # Secret dans remoteEnv
        assert content["remoteEnv"]["ANTHROPIC_API_KEY"] == "sk-secret-value"
        # Secret ABSENT des options de features
        features_str = json.dumps(content.get("features", {}))
        assert "sk-secret-value" not in features_str
    finally:
        shutil.rmtree(dc_path.parent, ignore_errors=True)


def test_write_devcontainer_missing_feature_dir_ignored(
    tmp_data_root, global_cfg, fake_devpod_bin
) -> None:
    """Une Feature dir absente dans /data/recipes est ignorée silencieusement."""
    import asyncio

    from portal.auth.router import provision_user
    from portal.devpod.service import DevPodService
    from portal.recipes.models import RecipeMeta

    asyncio.run(provision_user(login="alice", sub="sub", data_root=tmp_data_root))
    recipe = RecipeMeta(id="nonexistent")
    svc = DevPodService(global_cfg=global_cfg, devpod_bin=fake_devpod_bin)
    dc_path = svc._write_devcontainer("alice", "alice-myapp", recipes=[recipe])
    try:
        content = json.loads(dc_path.read_text(encoding="utf-8"))
        assert "features" not in content
    finally:
        shutil.rmtree(dc_path.parent, ignore_errors=True)
