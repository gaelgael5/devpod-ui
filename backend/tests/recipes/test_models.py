# backend/tests/recipes/test_models.py
from __future__ import annotations

import pytest
import yaml


_NODEJS_KEY = "08d27187-d87f-4140-a65e-0891b59441f1"


def test_recipe_meta_valid() -> None:
    from portal.recipes.models import RecipeMeta

    meta = RecipeMeta(
        id="claude-code",
        version="1.0.0",
        description="Claude Code CLI",
        requires_secrets=[{"path": "llm/anthropic_key", "env": "ANTHROPIC_API_KEY"}],
        installs_after=[_NODEJS_KEY],
    )
    assert meta.id == "claude-code"
    assert meta.installs_after == [_NODEJS_KEY]
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
        "key": "ff184539-18c7-4849-9ef3-943174113c49",
        "version": "1.0.0",
        "description": "Claude Code CLI",
        "requires_secrets": [{"path": "llm/anthropic_key", "env": "ANTHROPIC_API_KEY"}],
        "installs_after": [_NODEJS_KEY],
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

    with pytest.raises(ValidationError, match="extra"):
        RecipeMeta(id="x", unknown_field="bad")


def test_installs_after_invalid_id_rejected() -> None:
    from pydantic import ValidationError

    from portal.recipes.models import RecipeMeta

    with pytest.raises(ValidationError, match="installs_after"):
        RecipeMeta(id="my-recipe", installs_after=["../evil"])


def test_recipe_meta_type_defaults_to_install() -> None:
    from portal.recipes.models import RecipeMeta

    meta = RecipeMeta(id="my-recipe")
    assert meta.type == "install"


def test_recipe_meta_type_start_accepted() -> None:
    from portal.recipes.models import RecipeMeta

    meta = RecipeMeta(id="claude-rc", type="start")
    assert meta.type == "start"


def test_recipe_meta_type_invalid_rejected() -> None:
    from pydantic import ValidationError

    from portal.recipes.models import RecipeMeta

    with pytest.raises(ValidationError):
        RecipeMeta(id="bad", type="unknown")
