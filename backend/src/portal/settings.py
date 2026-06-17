from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Mode développement local (désactive https_only et autorise session key vide)
    dev_mode: bool = False

    # Session (cookie signé)
    session_secret_key: str = ""

    # OIDC
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "https://dev.yoops.org/auth/callback"
    oidc_role_claim: str = "realm_access.roles"
    oidc_admin_role: str = "admin"
    oidc_user_role: str = "dev"
    oidc_username_claim: str = "preferred_username"
    oidc_leeway: int = 30  # secondes

    # Auth locale (fallback sans OIDC)
    local_user: str = ""
    local_password: str = ""
    local_password_hash: str = ""

    portal_data_root: str = "/data"
    scripts_dir: str = "/app/scripts"
    bundled_recipes_dir: str = "/app/recipes"
    portal_api_key: str = ""

    # Base de données PostgreSQL (format : postgresql+asyncpg://user:pass@host/db)
    database_url: str = ""


_settings: AppSettings | None = None


def get_settings() -> AppSettings:
    global _settings
    if _settings is None:
        _settings = AppSettings()
    return _settings
