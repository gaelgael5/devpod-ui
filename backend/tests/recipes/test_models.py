# backend/tests/recipes/test_models.py
from __future__ import annotations

import pytest
import yaml


def test_recipe_meta_valid() -> None:
    from portal.recipes.models import RecipeMeta

    meta = RecipeMeta(
        id="claude-code",
        version="1.0.0",
        description="Claude Code CLI",
        requires_secrets=[{"path": "llm/anthropic_key", "env": "ANTHROPIC_API_KEY"}],
        installs_after=["node"],
    )
    assert meta.id == "claude-code"
    assert meta.requires_secrets[0].path == "llm/anthropic_key"
    assert meta.requires_secrets[0].env == "ANTHROPIC_API_KEY"


def test_recipe_meta_id_invalid() -> None:
    from pydantic import ValidationError

    from portal.recipes.models import RecipeMeta

    with pytest.raises(ValidationError, match="id"):
        RecipeMeta(id="INVALID NAME!")


def test_secret_ref_string_shorthand() -> None:
    from portal.recipes.models import RecipeMeta

    meta = RecipeMeta(id="aider", requires_secrets=["llm/anthropic_key"])
    assert meta.requires_secrets[0].path == "llm/anthropic_key"
    assert meta.requires_secrets[0].env == "LLM_ANTHROPIC_KEY"


def test_secret_ref_path_with_hyphen_normalised() -> None:
    from portal.recipes.models import RecipeMeta

    meta = RecipeMeta(id="aider", requires_secrets=["llm/gemini-key"])
    assert meta.requires_secrets[0].env == "LLM_GEMINI_KEY"


def test_secret_ref_invalid_path_rejected() -> None:
    from pydantic import ValidationError

    from portal.recipes.models import SecretRef

    with pytest.raises(ValidationError, match="secret path"):
        SecretRef(path="../traversal", env="TEST_VAR")


def test_secret_ref_invalid_env_rejected() -> None:
    from pydantic import ValidationError

    from portal.recipes.models import SecretRef

    with pytest.raises(ValidationError, match="env var"):
        SecretRef(path="my/secret", env="lowercase_not_allowed")


def test_recipe_option_defaults() -> None:
    from portal.recipes.models import RecipeOption

    opt = RecipeOption()
    assert opt.type == "string"
    assert opt.default == ""


def test_recipe_meta_from_yaml(tmp_path) -> None:
    from portal.recipes.models import RecipeMeta

    data = {
        "id": "claude-code",
        "version": "1.0.0",
        "description": "Claude Code CLI",
        "requires_secrets": [{"path": "llm/anthropic_key", "env": "ANTHROPIC_API_KEY"}],
        "installs_after": ["node"],
        "options": {"version": {"type": "string", "default": "latest"}},
    }
    meta_file = tmp_path / "recipe.meta.yaml"
    meta_file.write_text(yaml.dump(data), encoding="utf-8")

    meta = RecipeMeta.from_yaml(meta_file)
    assert meta.id == "claude-code"
    assert meta.options["version"].default == "latest"


def test_recipe_meta_extra_fields_rejected() -> None:
    from pydantic import ValidationError

    from portal.recipes.models import RecipeMeta

    with pytest.raises(ValidationError):
        RecipeMeta(id="x", unknown_field="bad")
