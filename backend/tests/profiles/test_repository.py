"""Tests du ProfileRepository sur un répertoire temporaire."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from portal.profiles.models import Profile, ProfileBody, ProfileSummary, Scope
from portal.profiles.repository import ProfileRepository, ProfileError, slugify


def test_slugify_basic() -> None:
    assert slugify("Frontend React") == "frontend-react"


def test_slugify_special_chars() -> None:
    assert slugify("React + TypeScript!") == "react-typescript"


def test_slugify_empty_fallback() -> None:
    assert slugify("!!!") == "profil"


def test_profile_body_defaults() -> None:
    body = ProfileBody(name="Test")
    assert body.description == ""
    assert body.extensions == []
    assert body.settings == {}


def test_profile_to_customizations() -> None:
    profile = Profile(
        slug="test",
        scope="user",
        name="Test",
        extensions=["ms-python.python"],
        settings={"editor.fontSize": 14},
    )
    result = profile.to_customizations()
    assert result == {
        "vscode": {
            "extensions": ["ms-python.python"],
            "settings": {"editor.fontSize": 14},
        }
    }
