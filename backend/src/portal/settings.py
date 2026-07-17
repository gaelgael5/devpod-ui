from __future__ import annotations

from urllib.parse import urlparse

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

    # Idle timeout GLISSANT (secondes) : max_age du cookie Starlette, réémis à
    # chaque réponse. Une session inactive plus longtemps est déconnectée ; toute
    # activité la prolonge (glissant depuis la DERNIÈRE requête). C'est ce qui
    # gouverne le confort terminal SSH / vue VS Code : tant que tu travailles, tu
    # n'es pas coupé. Défaut : 7200 s (2 h). Env : SESSION_MAX_AGE.
    session_max_age: int = 7200

    # Plafond d'âge ABSOLU depuis le login (secondes) — DÉCOUPLÉ de l'idle ci-dessus
    # (bug 032). Borne supérieure indépendante de l'activité : au-delà, un re-login
    # OIDC est forcé pour rafraîchir les rôles Keycloak (une révocation se propage
    # donc en au plus cette durée). Vérifié par rbac.session_within_max_age, appliqué
    # aussi aux proxies interactifs (VS Code, SSH). Volontairement LARGE pour ne pas
    # couper un utilisateur actif — le confort est déjà géré par l'idle glissant.
    # Défaut : 43200 s (12 h). Env : SESSION_ABSOLUTE_MAX_AGE.
    session_absolute_max_age: int = 43200

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

    # Dev only (nécessite dev_mode=true) : PIN utilisé pour initialiser/déverrouiller
    # automatiquement le vault de chaque utilisateur — évite de ressaisir un PIN à
    # chaque redémarrage sur une VM de test éphémère. Vide = comportement normal
    # (l'utilisateur choisit son propre PIN). Ignoré si dev_mode=false.
    vault_dev_pin: str = ""

    # MCP : intervalle de la boucle de monitoring des backends (secondes).
    mcp_monitor_interval_s: float = 300.0

    # skills.sh : URL de base de l'API tierce (surchargée en test/mock).
    skills_sh_base_url: str = "https://skills.sh"
    # Contenu canonique des SKILL.md (même source que `npx skills add`).
    skills_raw_base_url: str = "https://raw.githubusercontent.com"

    # MCP transport SSE : délai de stabilisation entre `initialize` et le premier
    # message applicatif. Certains serveurs SSE (ex. docflow) n'ont pas encore
    # démarré leur boucle de dispatch de messages quand le handshake se termine :
    # le premier appel envoyé trop tôt est perdu et la session meurt (le writer
    # tombe sur une connexion fermée). Le seul point d'action est un court settle
    # in-session — même logique que le settle du port-forward SSH. Observé : 0,2 s
    # suffit ; 0,5 s laisse une marge. Ne concerne que le transport `sse`.
    mcp_sse_init_settle_s: float = 0.5


def _common_domain_suffix(host_a: str, host_b: str) -> str:
    """Plus long suffixe de labels DNS commun à deux hôtes.

    Retourne "" si le suffixe commun fait moins de deux labels : un cookie sur un
    TLD nu serait rejeté par les navigateurs.
    """
    labels_a = host_a.lower().strip(".").split(".")
    labels_b = host_b.lower().strip(".").split(".")
    common: list[str] = []
    for la, lb in zip(reversed(labels_a), reversed(labels_b), strict=False):
        if la != lb:
            break
        common.append(la)
    if len(common) < 2:
        return ""
    return ".".join(reversed(common))


def resolve_cookie_domain(
    cookie_domain: str,
    base_domain: str,
    external_url: str = "",
    vs_proxy_domain: str = "",
) -> str | None:
    """Domaine du cookie de session, pour le transmettre aux workspaces (forward_auth).

    `cookie_domain` explicite prime (cas où portail et workspaces n'ont qu'un ancêtre
    commun). Sinon, si `vs_proxy_domain` est configuré, l'ancêtre DNS commun entre
    l'hôte de `external_url` et `vs_proxy_domain` est dérivé : sans cela le cookie
    (host-only ou limité à base_domain) n'atteint jamais le proxy VS Code et chaque
    ouverture retombe sur la page de login. En dernier recours : `base_domain`.
    Retourne ".{domaine}" ou None si rien n'est résoluble.
    """
    explicit = cookie_domain.strip()
    if explicit:
        return f".{explicit}"
    vs_host = vs_proxy_domain.strip()
    portal_host = urlparse(external_url.strip()).hostname or ""
    if vs_host and portal_host:
        derived = _common_domain_suffix(portal_host, vs_host)
        if derived:
            return f".{derived}"
    base = base_domain.strip()
    return f".{base}" if base else None


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


def update_cookie_domain(
    cookie_domain: str,
    base_domain: str,
    external_url: str = "",
    vs_proxy_domain: str = "",
) -> None:
    """Met à jour le domaine effectif du cookie de session.

    Même logique de priorité que resolve_cookie_domain (cookie_domain explicite,
    puis ancêtre commun portail/vs_proxy_domain, puis base_domain).
    Appelable depuis create_app() et PUT /admin/network sans redémarrage.
    """
    global _effective_cookie_domain
    _effective_cookie_domain = resolve_cookie_domain(
        cookie_domain, base_domain, external_url, vs_proxy_domain
    )


def get_effective_cookie_domain() -> str | None:
    """Domaine effectif courant du cookie de session (lu par _PortalSessionMiddleware)."""
    return _effective_cookie_domain
