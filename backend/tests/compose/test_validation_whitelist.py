"""Tests whitelist bind-mounts pour templates builtin (spec 30 §3.3)."""

from __future__ import annotations

import pytest

from portal.compose.validation import TemplateValidationError, validate_template

_ALLOY_COMPOSE = """
services:
  alloy:
    image: grafana/alloy:v1.5.1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /var/log:/var/log:ro
      - /run/log/journal:/run/log/journal:ro
      - /etc/machine-id:/etc/machine-id:ro
      - alloy_data:/var/lib/alloy/data
volumes:
  alloy_data:
"""


def test_builtin_allows_whitelisted_bind_mounts() -> None:
    validate_template(_ALLOY_COMPOSE, [], source="builtin")


def test_imported_allows_whitelisted_bind_mounts() -> None:
    # Import galerie validé par un admin — même confiance que builtin pour la
    # whitelist système fixe (spec 30 §3.3 étendue à l'import réseau).
    validate_template(_ALLOY_COMPOSE, [], source="imported")


def test_user_rejects_whitelisted_bind_mounts() -> None:
    with pytest.raises(TemplateValidationError, match="bind-mount absolu interdit"):
        validate_template(_ALLOY_COMPOSE, [], source="user")


def test_imported_rejects_non_whitelisted_bind_mount() -> None:
    content = """
services:
  svc:
    image: my/image:1.0.0
    volumes:
      - /etc/passwd:/etc/passwd:ro
"""
    with pytest.raises(TemplateValidationError, match="bind-mount absolu interdit"):
        validate_template(content, [], source="imported")


def test_builtin_rejects_non_whitelisted_bind_mount() -> None:
    content = """
services:
  svc:
    image: my/image:1.0.0
    volumes:
      - /etc/passwd:/etc/passwd:ro
"""
    with pytest.raises(TemplateValidationError, match="bind-mount absolu interdit"):
        validate_template(content, [], source="builtin")


def test_user_rejects_non_whitelisted_bind_mount() -> None:
    content = """
services:
  svc:
    image: my/image:1.0.0
    volumes:
      - /etc/passwd:/etc/passwd:ro
"""
    with pytest.raises(TemplateValidationError, match="bind-mount absolu interdit"):
        validate_template(content, [], source="user")
