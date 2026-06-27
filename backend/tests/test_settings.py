from __future__ import annotations

import pytest


def test_settings_default_values(monkeypatch: pytest.MonkeyPatch) -> None:
    import portal.settings as mod

    # Ensure env vars asserted as empty/default are absent — other tests may
    # set them via os.environ without cleanup (pre-existing pattern in the suite).
    monkeypatch.delenv("SESSION_SECRET_KEY", raising=False)
    monkeypatch.delenv("OIDC_LEEWAY", raising=False)
    mod._settings = None
    settings = mod.get_settings()
    assert settings.oidc_leeway == 30
    assert settings.session_secret_key == ""
    mod._settings = None


def test_settings_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_SECRET_KEY", "supersecret")
    monkeypatch.setenv("OIDC_ISSUER", "https://kc.example.com/realms/test")
    import portal.settings as mod

    mod._settings = None
    settings = mod.get_settings()
    assert settings.session_secret_key == "supersecret"
    assert settings.oidc_issuer == "https://kc.example.com/realms/test"
    mod._settings = None
