"""Validation du champ image de ProfileBody (référence OCI stricte)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.profiles.models import ProfileBody


def test_le_nom_accepte_la_barre_oblique() -> None:
    """« C/C++ Dev » est un libellé, pas un chemin : le chemin est dérivé du
    SLUG, validé séparément. Le refuser rendait 4 profils de la galerie
    silencieusement absents du catalogue (bug 511a465f)."""
    assert ProfileBody(name="C/C++ Dev").name == "C/C++ Dev"
    assert ProfileBody(name="TypeScript / Node.js").name == "TypeScript / Node.js"


def test_image_empty_is_default() -> None:
    assert ProfileBody(name="P").image == ""
    assert ProfileBody(name="P", image="  ").image == ""


def test_image_accepts_common_references() -> None:
    for ref in (
        "ubuntu",
        "ubuntu:24.04",
        "mcr.microsoft.com/devcontainers/python:3.12",
        "ghcr.io/org/image:v1.2.3",
        "registry.local:5000/team/app:latest",
        "python@sha256:" + "a" * 64,
    ):
        assert ProfileBody(name="P", image=ref).image == ref


def test_image_rejects_garbage() -> None:
    for ref in (
        "-rm",
        "image with spaces",
        "UPPER/Case:tag",  # repo en majuscules interdit par la grammaire OCI
        "img:tag; rm -rf /",
        "a" * 401,
        "http://registry/image",
    ):
        with pytest.raises(ValidationError):
            ProfileBody(name="P", image=ref)


def test_image_user_default_empty() -> None:
    assert ProfileBody(name="P").image_user == ""
    assert ProfileBody(name="P", image_user="  ").image_user == ""


def test_image_user_accepts_valid_logins() -> None:
    for u in ("vscode", "dev", "node", "app_user", "user-1"):
        assert ProfileBody(name="P", image_user=u).image_user == u


def test_image_user_rejects_invalid() -> None:
    for bad in ("Root", "1abc", "a b", "user!", "x" * 40):
        with pytest.raises(ValidationError):
            ProfileBody(name="P", image_user=bad)
