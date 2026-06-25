# backend/tests/test_mcp_app_url_grant.py
"""Modèles MCP : app_url (backend) + enabled (grant)."""
from __future__ import annotations

import pytest

from portal.mcp.models import BackendCreate, BackendUpdate, GrantSet


def test_backend_create_app_url_optional_default_empty() -> None:
    b = BackendCreate(namespace="ns", name="n", url="https://x")
    assert b.app_url == ""


def test_backend_create_app_url_accepts_http_s() -> None:
    b = BackendCreate(namespace="ns", name="n", url="https://x", app_url="https://app.example.com")
    assert b.app_url == "https://app.example.com"


def test_backend_create_app_url_rejects_non_url() -> None:
    with pytest.raises(ValueError):
        BackendCreate(namespace="ns", name="n", url="https://x", app_url="notaurl")


def test_backend_update_app_url() -> None:
    b = BackendUpdate(
        name="n", url="https://x", transport="streamable_http", enabled=True, app_url="http://a.lan"
    )
    assert b.app_url == "http://a.lan"


def test_grant_set_enabled_default_true() -> None:
    assert GrantSet(backend_id="b").enabled is True


def test_grant_set_enabled_false() -> None:
    assert GrantSet(backend_id="b", enabled=False).enabled is False
