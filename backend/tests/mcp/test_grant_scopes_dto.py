# backend/tests/mcp/test_grant_scopes_dto.py
"""DTO GrantSet : scopes optionnels, validés contre read/write/exec/admin."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.mcp.models import GrantSet


def test_scopes_default_none() -> None:
    assert GrantSet(backend_id="b").scopes is None


def test_scopes_accepted() -> None:
    assert GrantSet(backend_id="b", scopes=["read", "admin"]).scopes == ["read", "admin"]


def test_invalid_scope_rejected() -> None:
    with pytest.raises(ValidationError):
        GrantSet(backend_id="b", scopes=["bogus"])
