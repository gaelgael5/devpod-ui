"""Validation du champ image de ProfileBody (référence OCI stricte)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.profiles.models import ProfileBody


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
