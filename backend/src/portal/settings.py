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

    # Domaine de base (env BASE_DOMAIN, ex. "dev.yoops.org"). Sert au host matcher Caddy
    # et, par défaut, au domaine du cookie de session.
    base_domain: str = ""

    # Domaine du cookie de session (env COOKIE_DOMAIN). À renseigner quand portail et
    # workspaces ne partagent qu'un ancêtre commun (ex. portail dev.yoops.org +
    # workspaces ws-x.yoops.org → COOKIE_DOMAIN=yoops.org). Vide → base_domain.
    cookie_domain: str = ""

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
    portal_api_key: str = ""

    # Base de données PostgreSQL (format : postgresql+asyncpg://user:pass@host/db)
    database_url: str = ""

    # Vault : KEK 32 bytes hex (64 chars). Obligatoire en production.
    portal_vault_kek: str = ""

    # MCP : intervalle de la boucle de monitoring des backends (secondes).
    mcp_monitor_interval_s: float = 300.0


def resolve_cookie_domain(cookie_domain: str, base_domain: str) -> str | None:
    """Domaine du cookie de session, pour le transmettre aux workspaces (forward_auth).

    `cookie_domain` explicite prime (cas où portail et workspaces n'ont qu'un ancêtre
    commun) ; sinon on retombe sur `base_domain`. Retourne ".{domaine}" ou None si vide.
    """
    src = (cookie_domain or base_domain).strip()
    return f".{src}" if src else None


_settings: AppSettings | None = None


def get_settings() -> AppSettings:
    global _settings
    if _settings is None:
        _settings = AppSettings()
    return _settings


# ─── Domaine effectif du cookie de session ────────────────────────────────────
# Initialisé depuis les settings (env) dans create_app(), mis à jour depuis la
# DB dans le lifespan et après chaque PUT /admin/network.
# Stocké ici (settings.py) pour éviter l'import circulaire app.py ↔ routes/admin.py.

_effective_cookie_domain: str | None = None


def update_cookie_domain(cookie_domain: str, base_domain: str) -> None:
    """Met à jour le domaine effectif du cookie de session.

    cookie_domain prime sur base_domain (même logique que resolve_cookie_domain).
    Appelable depuis create_app() et PUT /admin/network sans redémarrage.
    """
    global _effective_cookie_domain
    _effective_cookie_domain = resolve_cookie_domain(cookie_domain, base_domain)


def get_effective_cookie_domain() -> str | None:
    """Domaine effectif courant du cookie de session (lu par _PortalSessionMiddleware)."""
    return _effective_cookie_domain
