# backend/tests/test_auth_flags.py
"""Flags d'auth exposés à la page de login : OIDC piloté par la config (DB),
login local piloté par le .env (settings)."""
from __future__ import annotations

from portal.auth.router import auth_flags
from portal.config.models import OidcConfig


def _oidc(issuer: str = "", client_id: str = "") -> OidcConfig:
    return OidcConfig(issuer=issuer, client_id=client_id, client_secret="")


def test_oidc_enabled_when_issuer_and_client_id_set() -> None:
    flags = auth_flags(_oidc("https://kc/realms/y", "workspace-portal"), "admin", "hash")
    assert flags["oidc_enabled"] is True


def test_oidc_disabled_when_issuer_missing() -> None:
    assert auth_flags(_oidc("", "workspace-portal"), "admin", "hash")["oidc_enabled"] is False


def test_oidc_disabled_when_client_id_missing() -> None:
    assert auth_flags(_oidc("https://kc/realms/y", ""), "admin", "hash")["oidc_enabled"] is False


def test_local_enabled_from_env_credentials() -> None:
    assert auth_flags(_oidc(), "admin", "hash")["local_auth_enabled"] is True
    assert auth_flags(_oidc(), "", "")["local_auth_enabled"] is False
