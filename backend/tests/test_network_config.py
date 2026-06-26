# backend/tests/test_network_config.py
"""Validation/normalisation de la config réseau (base_domain, external_url, workspace_host)."""
from __future__ import annotations

import pytest

from portal.config.models import validate_network


def test_accepts_valid_values() -> None:
    assert validate_network("dev.yoops.org", "https://dev.yoops.org/", "192.168.10.50") == {
        "base_domain": "dev.yoops.org",
        "external_url": "https://dev.yoops.org",
        "workspace_host": "192.168.10.50",
    }


def test_allows_all_empty() -> None:
    # Config "désactivée" : tout vide reste valide (pas de routage par sous-domaine).
    assert validate_network("", "", "") == {
        "base_domain": "",
        "external_url": "",
        "workspace_host": "",
    }


def test_strips_and_trims_trailing_slash() -> None:
    out = validate_network("  dev.yoops.org ", " https://dev.yoops.org/ ", "  ")
    assert out["base_domain"] == "dev.yoops.org"
    assert out["external_url"] == "https://dev.yoops.org"
    assert out["workspace_host"] == ""


def test_rejects_invalid_base_domain() -> None:
    with pytest.raises(ValueError):
        validate_network("pas un domaine!", "https://x.org", "")


def test_rejects_external_url_without_scheme() -> None:
    with pytest.raises(ValueError):
        validate_network("dev.yoops.org", "dev.yoops.org", "")


def test_rejects_external_url_with_bad_scheme() -> None:
    with pytest.raises(ValueError):
        validate_network("dev.yoops.org", "ftp://dev.yoops.org", "")
