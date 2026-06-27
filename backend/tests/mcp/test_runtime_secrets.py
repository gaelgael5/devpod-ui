from __future__ import annotations

import pytest

from portal.mcp import runtime_secrets
from portal.mcp.runtime_secrets import UnresolvableSecret, encrypt_service_key, resolve_grant_key
from portal.secrets.types import Secret

pytestmark_kek = lambda mp: mp.setattr(  # noqa: E731
    "portal.settings.get_settings", lambda: type("S", (), {"portal_vault_kek": "33" * 32})()
)


def test_encrypt_decrypt_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(
        "portal.settings.get_settings",
        lambda: type("S", (), {"portal_vault_kek": "11" * 32})(),
    )
    blob = runtime_secrets.encrypt_service_key("rag-token-123")
    assert isinstance(blob, bytes)
    assert blob != b"rag-token-123"
    assert runtime_secrets.decrypt_service_key(blob) == "rag-token-123"


def test_missing_kek_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "portal.settings.get_settings",
        lambda: type("S", (), {"portal_vault_kek": ""})(),
    )
    with pytest.raises(runtime_secrets.KekUnavailable):
        runtime_secrets.encrypt_service_key("x")


async def test_resolve_public_backend_returns_none() -> None:
    assert await resolve_grant_key(None) is None


async def test_resolve_local_key(monkeypatch) -> None:
    pytestmark_kek(monkeypatch)
    blob = encrypt_service_key("tok-abc")
    row = {"storage_type": "local", "secret_value_local": blob, "secret_value_vault_ref": None}
    out = await resolve_grant_key(row)
    assert isinstance(out, Secret) and out.reveal() == "tok-abc"


async def test_resolve_env_ref(monkeypatch) -> None:
    monkeypatch.setenv("MCP_RAG_TOKEN", "env-tok")
    row = {
        "storage_type": "harpocrate",
        "secret_value_local": None,
        "secret_value_vault_ref": "${env://MCP_RAG_TOKEN}",
    }
    out = await resolve_grant_key(row)
    assert out.reveal() == "env-tok"


async def test_resolve_harpocrate_vault_unresolvable() -> None:
    row = {
        "storage_type": "harpocrate",
        "secret_value_local": None,
        "secret_value_vault_ref": "${vault://wallet:mcp/b1/read}",
    }
    with pytest.raises(UnresolvableSecret):
        await resolve_grant_key(row)


async def test_resolve_unknown_storage_type() -> None:
    row = {"storage_type": "bogus", "secret_value_local": None, "secret_value_vault_ref": None}
    with pytest.raises(UnresolvableSecret):
        await resolve_grant_key(row)
