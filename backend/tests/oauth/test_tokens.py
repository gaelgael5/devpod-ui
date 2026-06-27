# backend/tests/oauth/test_tokens.py
from __future__ import annotations

from portal.mcp.service import token_hash
from portal.oauth.tokens import new_client_id, new_secret, sha256_hex


def test_new_secret_has_prefix_and_is_unique() -> None:
    a = new_secret("mcpk_")
    b = new_secret("mcpk_")
    assert a.startswith("mcpk_")
    assert a != b


def test_sha256_hex_matches_mcp_service() -> None:
    # Le token OAuth est une apikey : son hash doit être trouvable par resolve_tenant.
    assert sha256_hex("hello-token") == token_hash("hello-token")


def test_new_client_id_prefix() -> None:
    assert new_client_id().startswith("mcpc_")
