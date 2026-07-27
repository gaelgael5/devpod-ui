"""Résolution des durées de session : override admin (GlobalConfig) > défaut env/settings."""

from __future__ import annotations

from unittest.mock import patch

from portal.config.models import AuthConfig, GlobalConfig, OidcConfig, ServerConfig


def _cfg(**server: object) -> GlobalConfig:
    return GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url="", **server),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
    )


def test_effective_idle_falls_back_to_settings_when_unset() -> None:
    from portal.config.store import effective_session_max_age

    with patch("portal.config.store.load_global", return_value=_cfg(session_max_age=0)):
        # 0 en config → défaut settings (7200).
        assert effective_session_max_age() == 7200


def test_effective_idle_uses_config_override() -> None:
    from portal.config.store import effective_session_max_age

    with patch("portal.config.store.load_global", return_value=_cfg(session_max_age=1800)):
        assert effective_session_max_age() == 1800


def test_effective_absolute_falls_back_and_overrides() -> None:
    from portal.config.store import effective_session_absolute_max_age

    with patch("portal.config.store.load_global", return_value=_cfg(session_absolute_max_age=0)):
        assert effective_session_absolute_max_age() == 43200
    with patch("portal.config.store.load_global", return_value=_cfg(session_absolute_max_age=3600)):
        assert effective_session_absolute_max_age() == 3600


def test_session_within_max_age_honours_config_override() -> None:
    """rbac lit le plafond absolu effectif : un override admin s'applique sans redémarrage."""
    import time

    from portal.auth.rbac import session_within_max_age

    # Plafond abaissé à 1000 s via config → une session de 2000 s est expirée.
    with patch("portal.config.store.load_global", return_value=_cfg(session_absolute_max_age=1000)):
        old = int(time.time()) - 2000
        assert session_within_max_age({"auth_time": old}) is False
        assert session_within_max_age({"auth_time": int(time.time())}) is True
