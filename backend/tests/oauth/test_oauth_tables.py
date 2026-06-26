# backend/tests/oauth/test_oauth_tables.py
"""Structure des tables OAuth (tourne sans DB)."""
from __future__ import annotations

from portal.db.tables import mcp_apikey, mcp_oauth_authcode, mcp_oauth_client


def test_apikey_has_oauth_columns() -> None:
    for name in ("kind", "client_id", "refresh_token_hash", "expires_at"):
        assert name in mcp_apikey.c


def test_oauth_client_columns() -> None:
    for name in ("client_id", "redirect_uris", "client_name", "client_metadata"):
        assert name in mcp_oauth_client.c


def test_oauth_authcode_columns() -> None:
    for name in ("code_hash", "client_id", "owner_login", "code_challenge", "grants", "used"):
        assert name in mcp_oauth_authcode.c


def test_oauth_db_accessors_importable() -> None:
    from portal.db import oauth

    for fn in (
        "insert_client",
        "get_client",
        "insert_authcode",
        "consume_authcode",
        "find_apikey_by_refresh_hash",
    ):
        assert callable(getattr(oauth, fn))
