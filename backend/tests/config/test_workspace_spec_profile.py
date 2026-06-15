from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_workspace_spec_accepts_profile() -> None:
    from portal.config.models import WorkspaceSpec

    spec = WorkspaceSpec(
        name="myapp",
        source="github.com/org/repo",
        profile={"scope": "shared", "slug": "python-dev"},
    )
    assert spec.profile is not None
    assert spec.profile.scope == "shared"
    assert spec.profile.slug == "python-dev"


def test_workspace_spec_profile_defaults_none() -> None:
    from portal.config.models import WorkspaceSpec

    spec = WorkspaceSpec(name="myapp", source="github.com/org/repo")
    assert spec.profile is None


def test_profile_ref_rejects_invalid_scope() -> None:
    from portal.config.models import ProfileRef

    with pytest.raises(ValidationError):
        ProfileRef(scope="invalid", slug="my-profile")


def test_profile_ref_forbids_extra_fields() -> None:
    from portal.config.models import ProfileRef

    with pytest.raises(ValidationError):
        ProfileRef(scope="shared", slug="x", unknown_field="oops")


def test_profile_ref_rejects_invalid_slug() -> None:
    from portal.config.models import ProfileRef

    with pytest.raises(ValidationError):
        ProfileRef(scope="shared", slug="../hack")

    with pytest.raises(ValidationError):
        ProfileRef(scope="shared", slug="")


def test_workspace_spec_retro_compat_without_profile() -> None:
    """Une spec YAML sans 'profile' se charge correctement (rétro-compat)."""
    import yaml

    from portal.config.models import WorkspaceSpec

    raw = yaml.safe_load(
        "name: myapp\nsource: github.com/org/repo\nrecipes: []\n"
    )
    spec = WorkspaceSpec.model_validate(raw)
    assert spec.profile is None
