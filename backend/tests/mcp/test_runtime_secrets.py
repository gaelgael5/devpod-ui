from __future__ import annotations

import pytest

from portal.mcp import runtime_secrets


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
