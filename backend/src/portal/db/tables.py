from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

# ─── Tour 1 : GlobalConfig ────────────────────────────────────────────────────

# Singleton : toujours une seule ligne (id = 1)
global_config = Table(
    "global_config",
    metadata,
    Column("id", Integer, primary_key=True, default=1),
    Column("version", Text, nullable=False),
    # ServerConfig
    Column("listen", Text, nullable=False, server_default="0.0.0.0:8080"),
    Column("base_domain", Text, nullable=False),
    Column("external_url", Text, nullable=False),
    Column("dev_mode", Boolean, nullable=False, server_default="false"),
    Column("workspace_host", Text, nullable=False, server_default=""),
    Column("local_domain", Text, nullable=False, server_default=""),
    Column("vs_proxy_domain", Text, nullable=False, server_default=""),
    Column("cookie_domain", Text, nullable=False, server_default=""),
    # Durées de session éditables en admin (0 = hériter du défaut settings/env), migration 073.
    Column("session_max_age", Integer, nullable=False, server_default="0"),
    Column("session_absolute_max_age", Integer, nullable=False, server_default="0"),
    # LogConfig
    Column("log_level", Text, nullable=False, server_default="info"),
    Column("log_format", Text, nullable=False, server_default="text"),
    Column("log_output", Text, nullable=False, server_default=""),
    # LogsConfig (Loki/Grafana — distinct du LogConfig structlog ci-dessus)
    Column("logs_enabled", Boolean, nullable=False, server_default="false"),
    Column("logs_loki_push_url", Text, nullable=False, server_default=""),
    Column("logs_loki_query_url", Text, nullable=False, server_default=""),
    Column("logs_grafana_url", Text, nullable=False, server_default=""),
    Column("logs_module", Text, nullable=False, server_default="devpod"),
    Column("logs_push_token", Text, nullable=False, server_default=""),
    Column("logs_grafana_oauth_client_id", Text, nullable=False, server_default="agflow-grafana"),
    Column("logs_grafana_oauth_client_secret", Text, nullable=False, server_default=""),
    # OidcConfig
    Column("oidc_issuer", Text, nullable=False),
    Column("oidc_client_id", Text, nullable=False),
    Column("oidc_client_secret", Text, nullable=False, server_default=""),
    Column("oidc_scopes", ARRAY(Text), nullable=False),
    Column("oidc_role_claim", Text, nullable=False, server_default="realm_access.roles"),
    Column("oidc_admin_role", Text, nullable=False, server_default="admin"),
    Column("oidc_user_role", Text, nullable=False, server_default="dev"),
    Column("oidc_username_claim", Text, nullable=False, server_default="preferred_username"),
    Column("oidc_allow_local_auth", Boolean, nullable=False, server_default="true"),
    # SecretsConfig
    Column("secrets_backend", Text, nullable=False, server_default="inline"),
    Column("harpocrate_url", Text, nullable=False, server_default=""),
    Column("harpocrate_api_key", Text, nullable=False, server_default=""),
    Column("harpocrate_base_path", Text, nullable=False, server_default="devpod"),
    # DevpodConfig
    Column("devpod_binary", Text, nullable=False, server_default="/usr/local/bin/devpod"),
    Column("devpod_client_cert_path", Text, nullable=False, server_default="/data/certs/portal"),
    Column("devpod_ide", Text, nullable=False, server_default="openvscode"),
    Column("devpod_idle_timeout", Text, nullable=False, server_default="2h"),
    Column("devpod_dotfiles", Text, nullable=False, server_default=""),
    # CaddyConfig
    Column("caddy_admin_api", Text, nullable=False, server_default="http://caddy:2019"),
    Column("caddy_portal_host", Text, nullable=False, server_default="portal"),
    # CloudflareManagerConfig
    Column("cf_url", Text, nullable=False, server_default=""),
    Column("cf_api_key", Text, nullable=False, server_default=""),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

hypervisor_types = Table(
    "hypervisor_types",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False, unique=True),
    Column("label", Text, nullable=False, server_default=""),
    Column("add_script", Text, nullable=False, server_default=""),
    Column("destroy_script", Text, nullable=False, server_default=""),
    Column("test_host_params", JSONB, nullable=False, server_default="{}"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

hypervisors = Table(
    "hypervisors",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False, unique=True),
    Column("address", Text, nullable=False),
    Column("ssh_user", Text, nullable=False, server_default="root"),
    Column("ssh_port", Integer, nullable=False, server_default="22"),
    Column("ssh_key_path", Text, nullable=False),
    Column("pve_node", Text, nullable=False, server_default="pve"),
    Column("hypervisor_type", Text, nullable=False, server_default=""),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

hosts = Table(
    "hosts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False, unique=True),
    Column("is_default", Boolean, nullable=False, server_default="false"),
    Column("type", Text, nullable=False),
    Column("docker_host", Text, nullable=False, server_default=""),
    Column("address", Text, nullable=False, server_default=""),
    Column("proxmox_node", Text, nullable=False, server_default=""),
    Column("vmid", Text, nullable=False, server_default=""),
    Column("ci_password_secret_slug", Text, nullable=False, server_default=""),
    Column("host_cert_slug", Text, nullable=False, server_default=""),
    # Cert client mTLS (docker-tls) : slug harpo_certificates tls-* (migration 071).
    Column("docker_cert_slug", Text, nullable=False, server_default=""),
    Column("storage_type", Text, nullable=False, server_default="local"),
    Column("vault_identifier", Text, nullable=False, server_default=""),
    Column("usage", Text, nullable=False, server_default="workspaces"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# ─── Tour 2 : Sources distantes ───────────────────────────────────────────────

recipe_sources = Table(
    "recipe_sources",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("url", Text, nullable=False, unique=True),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

profile_sources = Table(
    "profile_sources",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("url", Text, nullable=False, unique=True),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# ─── Tour 3 : Tokens de jointure nœuds ────────────────────────────────────────

node_join_tokens = Table(
    "node_join_tokens",
    metadata,
    Column("token_hash", Text, primary_key=True),
    Column("node_name", Text, nullable=False),
    Column("address", Text, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used", Boolean, nullable=False, server_default="false"),
    Column("used_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# ─── Tour 4 : UserConfig ──────────────────────────────────────────────────────

users = Table(
    "users",
    metadata,
    Column("login", Text, primary_key=True),
    Column("version", Text, nullable=False),
    Column("secret_ns", UUID(as_uuid=False), nullable=False, unique=True),
    Column("default_ide", Text, nullable=False, server_default="openvscode"),
    Column("default_idle_timeout", Text, nullable=False, server_default="4h"),
    Column("harpocrate_api_key", Text, nullable=False, server_default=""),
    Column("culture", Text, nullable=False, server_default="fr"),
    Column("email", Text, nullable=False, server_default=""),
    Column("display_name", Text, nullable=False, server_default=""),
    # Sujet OIDC (claim `sub`) : ancre d'identité STABLE, contrairement au
    # preferred_username (dérive le login) et à l'email (peut changer/collision).
    # Nullable : les comptes existants n'en ont pas encore — backfillé au 1er
    # login OIDC (migration 068). UNIQUE : un sub ↔ au plus un login.
    Column("sub", Text, nullable=True, unique=True),
    # Identité propagée aux services MCP (on-behalf-of, cf. mcp/obo) : GUID éditable
    # par l'utilisateur dans son profil. Défaut effectif = `sub` OIDC quand vide (voir
    # get_user_actor). Nécessaire pour les comptes LOCAUX (sans sub), qui peuvent ainsi
    # se donner un identifiant portable aligné sur les services. UNIQUE (anti-collision).
    Column("identity", Text, nullable=True, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

git_credentials = Table(
    "git_credentials",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("host", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("key_path", Text, nullable=False, server_default=""),
    Column("public_key", Text, nullable=False, server_default=""),
    Column("username", Text, nullable=False, server_default=""),
    Column("token", Text, nullable=False, server_default=""),
)

workspaces = Table(
    "workspaces",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("branch", Text, nullable=False, server_default=""),
    Column("git_credential", Text, nullable=False, server_default=""),
    Column("host", Text, nullable=False, server_default=""),
    Column("template", Text, nullable=False, server_default=""),
    Column("devcontainer_path", Text, nullable=False, server_default=""),
    Column("recipes", ARRAY(Text), nullable=False, server_default="{}"),
    Column("ide", Text, nullable=False, server_default=""),
    Column("idle_timeout", Text, nullable=False, server_default=""),
    Column("env", JSONB, nullable=False, server_default="{}"),
    Column("expose_hostname", Text, nullable=False, server_default=""),
    Column("ssh_key", Boolean, nullable=False, server_default="false"),
    Column("profile_scope", Text, nullable=True),
    Column("profile_slug", Text, nullable=True),
    Column("start_recipes", ARRAY(Text), nullable=False, server_default="{}"),
    Column("default_start", Text, nullable=False, server_default=""),
    Column("recipe_volumes", ARRAY(Text), nullable=False, server_default="{}"),
    Column("init_recipes", ARRAY(Text), nullable=False, server_default="{}"),
    Column("groups", ARRAY(Text), nullable=False, server_default="{}"),
    # Spec 35 : types d'agents à configurer (accès MCP direct).
    Column("agents", ARRAY(Text), nullable=False, server_default="{}"),
    # Épingle « garder actif » (enabler 6016436b, migration 080) : jamais de
    # suggestion d'arrêt pour inactivité sur ce workspace.
    Column("keep_active", Boolean, nullable=False, server_default="false"),
    # Surcharge de la limite mémoire du conteneur (enabler 59864c37, migration
    # 081) : docker --memory ; "" = hériter du défaut global.
    Column("memory_limit", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("login", "name", name="uq_workspaces_login_name"),
)

workspace_group = Table(
    "workspace_group",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("login", "name", name="uq_workspace_group_login_name"),
)

workspace_extra_sources = Table(
    "workspace_extra_sources",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "workspace_id", Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    ),
    Column("position", Integer, nullable=False),
    Column("url", Text, nullable=False),
    Column("branch", Text, nullable=False, server_default=""),
    Column("git_credential", Text, nullable=False, server_default=""),
)

# Association VM de test ↔ workspace propriétaire (lot C+D du système de VM de test).
workspace_test_hosts = Table(
    "workspace_test_hosts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("login", Text, nullable=False),
    Column("workspace_name", Text, nullable=False),
    Column("host_name", Text, nullable=False),
    # Alias court `testN` (par workspace), pour `ssh testN` dans le container.
    Column("alias", Text, nullable=True),
    Column("message_id", BigInteger, nullable=True),
    # NULL = ligne du workspace PROPRIÉTAIRE (créateur de la VM, pilote son cycle
    # de vie) ; non-NULL = ligne de PARTAGE, valeur = nom du workspace d'origine.
    Column("shared_from_workspace", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("login", "workspace_name", "host_name", name="uq_wth_login_ws_host"),
)

# Liens (clé → URL) attachés à un serveur de test — affichés dans le menu ⋮ du host.
test_host_links = Table(
    "test_host_links",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "test_host_id",
        Integer,
        ForeignKey("workspace_test_hosts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("key", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("test_host_id", "key", name="uq_thl_host_key"),
)

# ─── Tour 10 : node_certificates (Groupe 4 — dépend de hosts) ───────────────

node_certificates = Table(
    "node_certificates",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("node_name", Text, nullable=False, unique=True),
    Column("address", Text, nullable=False),
    Column("cert_pem", Text, nullable=False),
    Column("serial_number", Text, nullable=False, server_default=""),
    Column("signed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
)

# ─── Tour 9 : workspace_log_blobs (option B — log complet par opération) ─────

workspace_log_blobs = Table(
    "workspace_log_blobs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ws_id", Text, nullable=False),
    Column("login", Text, nullable=False),
    Column("operation", Text, nullable=False, server_default="up"),
    Column("content", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("ws_id", "operation", "started_at", name="uq_workspace_log_blobs"),
)

# ─── Tour 8 : workspace_ssh_keys ─────────────────────────────────────────────

workspace_ssh_keys = Table(
    "workspace_ssh_keys",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("login", Text, nullable=False),
    Column("workspace_name", Text, nullable=False),
    Column("private_key_path", Text, nullable=False),
    Column("public_key", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["login", "workspace_name"],
        ["workspaces.login", "workspaces.name"],
        ondelete="CASCADE",
        name="fk_workspace_ssh_keys_workspace",
    ),
    UniqueConstraint("login", "workspace_name", name="uq_workspace_ssh_keys_login_ws"),
)

# ─── Tour 7 : recipes (métadonnées — scripts restent filesystem) ─────────────

recipes = Table(
    "recipes",
    metadata,
    Column("id", Text, nullable=False),
    # login_key = login or '' — PK composite sans NULL
    Column("login_key", Text, nullable=False, server_default=""),
    Column("scope", Text, nullable=False, server_default="shared"),
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=True),
    Column("key", Text, nullable=False),  # UUID stable, UNIQUE
    Column("type", Text, nullable=False, server_default="install"),
    Column("version", Text, nullable=False, server_default="1.0.0"),
    Column("description", Text, nullable=False, server_default=""),
    Column("options", JSONB, nullable=False, server_default="{}"),
    Column("requires_secrets", JSONB, nullable=False, server_default="[]"),
    Column("installs_after", ARRAY(Text), nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# ─── Tour 6 : workspace_status ───────────────────────────────────────────────

workspace_status = Table(
    "workspace_status",
    metadata,
    Column("ws_id", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("login", Text, nullable=False, server_default=""),
    Column("host_port", Integer, nullable=True),
    Column("host_type", Text, nullable=True),
    Column("host_name", Text, nullable=True),
    Column("url", Text, nullable=True),
    Column("hostname", Text, nullable=True),
    Column("returncode", Integer, nullable=True),
    Column("error", Text, nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Inactivité des workspaces (enabler 6016436b, migration 080) : période d'idle
# continue observée par sessions/idle.py. Une ligne = un workspace actuellement
# inactif ; supprimée dès qu'une activité reprend (ou pin / stop). alerted_at
# non nul = l'alerte de cette période a déjà été émise (une seule par période).
workspace_idle = Table(
    "workspace_idle",
    metadata,
    Column("ws_id", Text, primary_key=True),
    Column("login", Text, nullable=False),
    Column("idle_since", DateTime(timezone=True), nullable=False),
    Column("last_activity", DateTime(timezone=True), nullable=True),
    Column("alerted_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Vivacité des hosts (enabler 727ee81d, migration 079) : posée par la sonde TCP
# périodique (nodes/liveness.py), lue par node_list. reachable NULL = jamais sondé.
host_health = Table(
    "host_health",
    metadata,
    Column("name", Text, primary_key=True),
    Column("reachable", Boolean, nullable=True),
    Column("last_seen", DateTime(timezone=True), nullable=True),
    Column("changed_at", DateTime(timezone=True), nullable=True),
)

# Empreinte de la dernière config agents livrée (migration 072) : le resync ne
# rotationne/réécrit que si elle change → moins de ré-authentifications MCP.
workspace_agent_sync = Table(
    "workspace_agent_sync",
    metadata,
    Column("ws_id", Text, primary_key=True),
    Column("config_hash", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# ─── Tour 5 : Profiles ────────────────────────────────────────────────────────

profiles = Table(
    "profiles",
    metadata,
    Column("slug", Text, nullable=False),
    Column("scope", Text, nullable=False),
    # login_key = login or '' — permet une PK composite sans NULL
    Column("login_key", Text, nullable=False, server_default=""),
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    # Image de base du devcontainer (vide = défaut du portail)
    Column("image", Text, nullable=False, server_default=""),
    Column("extensions", ARRAY(Text), nullable=False, server_default="{}"),
    Column("settings", JSONB, nullable=False, server_default="{}"),
    Column("gallery_source", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# ─── Phase 2 : Vault PIN utilisateur ─────────────────────────────────────────

user_pin_config = Table(
    "user_pin_config",
    metadata,
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), primary_key=True),
    Column("encrypted_master_key", LargeBinary, nullable=False),
    Column("pin_salt", LargeBinary, nullable=False),
    Column("encrypted_master_key_recovery", LargeBinary, nullable=False),
    Column("recovery_salt", LargeBinary, nullable=False),
    Column("pin_attempts", Integer, nullable=False, server_default="0"),
    Column("locked_until", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

user_harpocrate_keys = Table(
    "user_harpocrate_keys",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("identifier", Text, nullable=False),
    Column("encrypted_token", LargeBinary, nullable=False),
    Column("url", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("login", "identifier", name="uq_user_harpocrate_keys_login_id"),
)

# ─── Tour 11 : harpo_certificates ────────────────────────────────────────────

harpo_certificates = Table(
    "harpo_certificates",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("slug", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    # ssh-ed25519 | ssh-rsa-2048 | ssh-rsa-4096 | ssh-ecdsa-p256
    # tls-rsa-2048 | tls-rsa-4096 | tls-ec-p256 | tls-ec-p384
    Column("cert_type", Text, nullable=False),
    Column("public_key", Text, nullable=False),
    # CA optionnel (public) : présent pour un bundle mTLS docker-tls importé
    # (cert client = public_key, clé = private_key_*, autorité = ca_pem).
    Column("ca_pem", Text, nullable=True),
    Column("private_key_local", LargeBinary, nullable=True),  # AES-GCM, master_key
    Column("private_key_vault_ref", Text, nullable=True),  # ${vault://id:certificats/slug/private}
    Column("storage_type", Text, nullable=False),  # local | harpocrate
    Column("vault_identifier", Text, nullable=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("is_public", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("owner_login", "slug", name="uq_harpo_certs_login_slug"),
)

# ─── Tour 12 : harpo_secrets ─────────────────────────────────────────────────

harpo_secrets = Table(
    "harpo_secrets",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("slug", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    # PAT_GITHUB | PAT_GITLAB | PAT_AZURE | API_KEY | … (extensible)
    Column("secret_type", Text, nullable=False),
    Column("secret_value_local", LargeBinary, nullable=True),
    Column("secret_value_vault_ref", Text, nullable=True),
    Column("storage_type", Text, nullable=False),
    Column("vault_identifier", Text, nullable=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("is_public", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("owner_login", "slug", name="uq_harpo_secrets_login_slug"),
)

# ─── MCP Gateway (lot 1) ──────────────────────────────────────────────────────

mcp_backend = Table(
    "mcp_backend",
    metadata,
    Column("id", Text, primary_key=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("namespace", Text, nullable=False),  # préfixe ^[a-z0-9_]+ sans "__"
    Column("name", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("transport", Text, nullable=False, server_default="streamable_http"),
    # Schéma d'authentification porté vers le backend : "bearer" (Authorization:
    # Bearer <clé>, défaut, standard MCP) ou "x_api_key" (X-API-Key: <clé>, pour
    # les serveurs non conformes qui exigent ce header, ex. gateway agflow).
    Column("auth_scheme", Text, nullable=False, server_default="bearer"),
    # Propager l'identité humaine (on-behalf-of signé) aux appels sortants. false
    # par défaut : on ne diffuse l'utilisateur qu'aux backends first-party de confiance
    # qui savent vérifier la signature (cf. mcp/obo). Requiert une clé (secret de signature).
    Column("forward_identity", Boolean, nullable=False, server_default="false"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    # URL web optionnelle de l'application (lien « ouvrir » dans la liste).
    Column("app_url", Text, nullable=False, server_default=""),
    # auth_scheme="oauth" : URL du serveur d'autorisation si elle diffère de l'URL
    # du MCP ; vide = découverte auto (.well-known/oauth-protected-resource).
    Column("oauth_auth_url", Text, nullable=False, server_default=""),
    # Opt-out de la protection anti rug-pull (quarantaine sur redéfinition, spec 23).
    # false par défaut : protection active. true = backend de confiance (service
    # exposé par l'utilisateur lui-même) → jamais de quarantaine, levée au resync.
    Column("quarantine_disabled", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("owner_login", "namespace", name="uq_mcp_backend_owner_namespace"),
)

mcp_backend_key = Table(
    "mcp_backend_key",
    metadata,
    Column("id", Text, primary_key=True),
    Column("backend_id", Text, ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
    Column("slug", Text, nullable=False),  # clef fonctionnelle, ex 'read'/'admin'
    Column("description", Text, nullable=False, server_default=""),
    Column("storage_type", Text, nullable=False),  # 'local' | 'harpocrate'
    Column("secret_value_local", LargeBinary, nullable=True),
    Column("secret_value_vault_ref", Text, nullable=True),
    Column("vault_identifier", Text, nullable=True),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("backend_id", "slug", name="uq_mcp_backend_key_backend_slug"),
)

mcp_profile = Table(
    "mcp_profile",
    metadata,
    Column("id", Text, primary_key=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    # Spec 35 : profil injecté dans les fichiers MCP des workspaces de son owner.
    Column("exposed_in_workspaces", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=True),
)

mcp_profile_entry = Table(
    "mcp_profile_entry",
    metadata,
    Column("profile_id", Text, ForeignKey("mcp_profile.id", ondelete="CASCADE"), nullable=False),
    Column("backend_id", Text, ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
    # Clé de service explicite ; null = auto-résolution (première clé enabled du backend).
    Column(
        "backend_key_id",
        Text,
        ForeignKey("mcp_backend_key.id", ondelete="SET NULL"),
        nullable=True,
    ),
    # null = tous les tools, [] = aucun, [...] = subset explicite.
    Column("tools", JSONB, nullable=True),
    UniqueConstraint("profile_id", "backend_id", name="uq_mcp_profile_entry"),
)

# Surcharge PERSISTANTE du profil d'un workspace (fiche persistance des choix) :
# le profil « exposé par défaut » alimente un workspace tant que l'utilisateur ne
# choisit rien ; dès qu'il fixe un profil sur la ligne (écran Client API Keys),
# ce choix est mémorisé ici et survit à la rotation des clefs (qui, elle, ne
# consulte que cette table quand une ligne existe). ws_id = convention "{login}-{name}"
# (pas de FK dure, comme workspace_ref) ; FK profil = CASCADE (profil supprimé →
# la surcharge disparaît → le workspace re-suit le défaut).
mcp_workspace_profile = Table(
    "mcp_workspace_profile",
    metadata,
    Column("ws_id", Text, primary_key=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("profile_id", Text, ForeignKey("mcp_profile.id", ondelete="CASCADE"), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

mcp_apikey = Table(
    "mcp_apikey",
    metadata,
    Column("id", Text, primary_key=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("token_hash", Text, nullable=False),  # sha256 hex du token clair
    Column("label", Text, nullable=False, server_default=""),
    Column("revoked", Boolean, nullable=False, server_default="false"),
    # Instant de révocation (NULL tant que non révoquée) — base de la purge à 24h.
    # Les lignes révoquées avant l'ajout de la colonne l'ont NULL : la purge retombe
    # alors sur created_at.
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # OAuth : un token émis par le flow OAuth est une apikey kind='oauth'.
    Column("kind", Text, nullable=False, server_default="apikey"),  # apikey | oauth
    Column("client_id", Text, nullable=True),  # client OAuth émetteur (informatif)
    Column("refresh_token_hash", Text, nullable=True),  # sha256 du refresh token
    Column("expires_at", DateTime(timezone=True), nullable=True),  # NULL = pas d'expiration
    # Profil MCP associé ; null = aucun accès (deny-by-default).
    Column(
        "profile_id",
        Text,
        ForeignKey("mcp_profile.id", ondelete="SET NULL"),
        nullable=True,
    ),
    # Spec 35 : clef générée pour un workspace (ws_id "{login}-{name}", convention
    # spec 34 — pas de FK dure). NULL = clef utilisateur classique.
    Column("workspace_ref", Text, nullable=True),
    Index(
        "idx_mcp_apikey_workspace_ref",
        "workspace_ref",
        postgresql_where=text("workspace_ref IS NOT NULL"),
    ),
)

# ─── Types d'agents workspace (spec 35) ──────────────────────────────────────

# Un type d'agent = un fichier de configuration MCP généré dans chaque workspace
# qui le demande : template Jinja (rendu sandboxé) + nom de fichier + chemin cible
# dans le conteneur. Les contraintes de format (slug, filename sans '/', target_path
# sans '..') sont validées côté pydantic (portal.agents.models).
agent_type = Table(
    "agent_type",
    metadata,
    Column("id", Text, primary_key=True),
    Column("label", Text, nullable=False),
    Column("filename", Text, nullable=False),
    Column("template", Text, nullable=False),
    Column("target_path", Text, nullable=False),
    # Stratégie de matérialisation : 'replace' (fichier dédié, symlink vers mount
    # ro) ou 'merge' (fichier partagé, fusion du connecteur). Cf. migration 058.
    Column("mode", Text, nullable=False, server_default="replace"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=True),
)

# ─── MCP Gateway (lot 2 — runtime) ───────────────────────────────────────────

mcp_tool_catalog = Table(
    "mcp_tool_catalog",
    metadata,
    Column("backend_id", Text, ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),  # 'tool' | 'resource' | 'prompt'
    Column("original_name", Text, nullable=False),
    Column("definition", JSONB, nullable=False),
    Column("definition_hash", Text, nullable=False),
    Column("first_seen", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_seen", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("quarantined", Boolean, nullable=False, server_default="false"),
    UniqueConstraint("backend_id", "kind", "original_name", name="pk_mcp_tool_catalog"),
)

mcp_audit_log = Table(
    "mcp_audit_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("apikey_id", Text, nullable=True),
    Column("owner_login", Text, nullable=True),
    Column("namespaced_name", Text, nullable=True),
    Column("backend_id", Text, nullable=True),
    Column("backend_key_id", Text, nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("status", Text, nullable=False),  # ok | error | denied | timeout
    Column("error", Text, nullable=True),
)

# ─── MCP Gateway OAuth (Authorization Server maison) ─────────────────────────

mcp_oauth_client = Table(
    "mcp_oauth_client",
    metadata,
    Column("client_id", Text, primary_key=True),
    Column("redirect_uris", JSONB, nullable=False, server_default="[]"),
    Column("client_name", Text, nullable=False, server_default=""),
    Column("client_metadata", JSONB, nullable=False, server_default="{}"),  # DCR brut
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

mcp_oauth_authcode = Table(
    "mcp_oauth_authcode",
    metadata,
    Column("code_hash", Text, primary_key=True),  # sha256 du code clair
    Column(
        "client_id",
        Text,
        ForeignKey("mcp_oauth_client.client_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("redirect_uri", Text, nullable=False),
    Column("code_challenge", Text, nullable=False),  # PKCE S256
    Column("scope", Text, nullable=False, server_default=""),
    Column("grants", JSONB, nullable=False, server_default="[]"),  # backends + curation choisis
    Column("profile_id", Text, nullable=True),  # profil sélectionné sur l'écran de consentement
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used", Boolean, nullable=False, server_default="false"),
)

# ─── MCP Gateway OAuth CLIENT (la gateway consomme un backend OAuth) ──────────
# Distinct de mcp_oauth_* ci-dessus (gateway = serveur d'autorisation). Ici la
# gateway est CLIENT OAuth 2.1 d'un backend amont (ex. Confluence). Auth par
# utilisateur, enregistrement dynamique (DCR), PKCE.

# Client OAuth enregistré (DCR) + métadonnées AS découvertes, un par backend.
mcp_backend_oauth_client = Table(
    "mcp_backend_oauth_client",
    metadata,
    Column(
        "backend_id",
        Text,
        ForeignKey("mcp_backend.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("issuer", Text, nullable=False),
    Column("authorization_endpoint", Text, nullable=False),
    Column("token_endpoint", Text, nullable=False),
    Column("registration_endpoint", Text, nullable=True),
    Column("client_id", Text, nullable=False),
    # Secret client éventuel (DCR confidentiel) chiffré KEK ; NULL = client public (PKCE seul).
    Column("client_secret_enc", LargeBinary, nullable=True),
    Column("scopes", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Token OAuth par (backend, utilisateur) — access + refresh chiffrés KEK.
mcp_backend_oauth_token = Table(
    "mcp_backend_oauth_token",
    metadata,
    Column("backend_id", Text, ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
    Column("user_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("access_token_enc", LargeBinary, nullable=False),
    Column("refresh_token_enc", LargeBinary, nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=True),  # NULL = pas d'expiration connue
    Column("scopes", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("backend_id", "user_login", name="uq_mcp_backend_oauth_token"),
)

# Requête d'autorisation en vol (entre le clic « Connecter » et le callback) :
# state anti-CSRF lié à (backend, user) + verifier PKCE. TTL court, usage unique.
mcp_backend_oauth_pending = Table(
    "mcp_backend_oauth_pending",
    metadata,
    Column("state", Text, primary_key=True),  # aléatoire, opaque
    Column("backend_id", Text, ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
    Column("user_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("code_verifier", Text, nullable=False),
    Column("redirect_uri", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

# ─── Compose Gallery : sources de la galerie ─────────────────────────────────

compose_catalog_sources = Table(
    "compose_catalog_sources",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("url", Text, nullable=False, unique=True),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# ─── Jinja Gallery : sources de la galerie de templates Jinja2 ───────────────

jinja_template_sources = Table(
    "jinja_template_sources",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("url", Text, nullable=False, unique=True),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# ─── Compose Gallery (lot 1) ─────────────────────────────────────────────────

compose_template = Table(
    "compose_template",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("tags", ARRAY(Text), nullable=False, server_default="{}"),
    Column("version", Text, nullable=False),
    Column("compose_content", Text, nullable=False),
    Column("parameters", JSONB, nullable=False, server_default="[]"),
    Column("source", Text, nullable=False),
    Column("extra_files", JSONB, nullable=False, server_default="{}"),
    Column("message_key", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

compose_deployment = Table(
    "compose_deployment",
    metadata,
    Column("uid", Text, primary_key=True),  # UUID généré à la création
    Column("id", Text, nullable=False),  # slug choisi par l'utilisateur
    Column("template_id", Text, ForeignKey("compose_template.id"), nullable=False),
    Column("template_version", Text, nullable=False),
    Column("node_id", Text, nullable=False),
    Column("owner_login", Text, nullable=False),
    Column("env_values", JSONB, nullable=False, server_default="{}"),
    Column("host_ports", ARRAY(Integer), nullable=False, server_default="{}"),
    Column("status", Text, nullable=False, server_default="created"),
    Column("last_error", Text, nullable=True),
    Column("message_id", BigInteger, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("id", "node_id", name="uq_compose_deployment_name_node"),
)

compose_deployment_log = Table(
    "compose_deployment_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("deployment_id", Text, nullable=False),
    Column("operation", Text, nullable=False),
    Column("content", Text, nullable=False, server_default=""),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True), nullable=True),
)

# Préférence utilisateur : déployer automatiquement ce template sur chaque
# nouvelle machine de test qu'il crée (lié à user + template, pas au host —
# voir cadrage utilisateur : la vignette est globale, le choix est personnel).
compose_auto_start = Table(
    "compose_auto_start",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column(
        "template_id", Text, ForeignKey("compose_template.id", ondelete="CASCADE"), nullable=False
    ),
    Column("env_values", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("owner_login", "template_id", name="uq_compose_auto_start_login_tpl"),
)

# ─── Système de messages contextuels pour agents ──────────────────────────────

jinja2_template = Table(
    "jinja2_template",
    metadata,
    Column("key", Text, nullable=False),
    Column("culture", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("key", "culture", name="pk_jinja2_template"),
)

workspace_message = Table(
    "workspace_message",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("owner_login", Text, nullable=False),
    Column("workspace_name", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


# ─── Spec 34 : messagerie inter-agents (délivrance pilotée par l'utilisateur) ──
#
# Référence de workspace par ws_id texte ("{login}-{name}"), comme workspace_status :
# workspaces.id est un entier réattribué à chaque save de config (delete+réinsertion),
# donc inutilisable en FK stable. owner_login scope les deux workspaces (v1 intra-user).
agent_message = Table(
    "agent_messages",
    metadata,
    Column("id", Text, primary_key=True),  # uuid4 généré côté Python (cf. compose_deployment)
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("owner_login", Text, nullable=False),
    Column("from_ws_id", Text, nullable=False),
    Column("from_session", Text, nullable=True),
    Column("to_ws_id", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("body", Text, nullable=False),
    # Fil de réponses : agent_messages est une table stable (lignes immuables une fois
    # créées), la self-FK est donc saine — SET NULL si le message parent disparaît.
    Column("reply_to", Text, ForeignKey("agent_messages.id", ondelete="SET NULL"), nullable=True),
    Column(
        "status",
        Text,
        nullable=False,
        server_default="pending",
    ),
    Column("delivered_at", DateTime(timezone=True), nullable=True),
    Column("delivered_to_session", Text, nullable=True),
    Column("cancelled_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("from_ws_id <> to_ws_id", name="ck_agent_messages_no_self"),
    CheckConstraint("char_length(subject) <= 200", name="ck_agent_messages_subject_len"),
    CheckConstraint("char_length(body) <= 20000", name="ck_agent_messages_body_len"),
    CheckConstraint(
        "status IN ('pending', 'delivered', 'cancelled')", name="ck_agent_messages_status"
    ),
    Index(
        "idx_agent_messages_to_pending",
        "to_ws_id",
        postgresql_where=text("status = 'pending'"),
    ),
    Index("idx_agent_messages_from", "from_ws_id", "created_at"),
    Index(
        "idx_agent_messages_reply_to",
        "reply_to",
        postgresql_where=text("reply_to IS NOT NULL"),
    ),
)


# ─── Outbox transactionnel du relais d'events workflow ───────────────────────
#
# Tampon durable entre l'écouteur du bus (qui n'y fait qu'insérer l'enveloppe,
# dans la même txn) et le worker de fond (qui signe HMAC + POST, hors txn DB —
# bug 026). `raw_body` = octets exacts sérialisés à signer ET poster. `status`
# ∈ {pending, delivered, failed} ; retry/backoff porté par next_attempt_at.
workflow_event_outbox = Table(
    "workflow_event_outbox",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("event_id", Text, nullable=False),
    Column("event_code", Text, nullable=False),
    Column("raw_body", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("last_error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("delivered_at", DateTime(timezone=True), nullable=True),
    Index("idx_workflow_event_outbox_due", "status", "next_attempt_at"),
)


# Journal durable et interne de chaque event métier (source consommée par les
# automates locaux). Écrit **inconditionnellement** à l'émission — indépendant de
# l'activation du producteur workflow (invariant 1 de l'epic Termix). `seq` donne
# l'ordre total et sert de curseur aux automates. Pas de FK sur workspace : le
# payload est auto-porteur (un event de suppression survit à l'objet disparu).
# `consumed_by` porte le chaînage stop_chain du moteur d'automates (renseigné à
# la consommation). `dedup_key` = clé naturelle de dédup exploitée en aval
# (once-per-version côté automation_run), pas une contrainte d'unicité ici : le
# journal enregistre tous les faits, y compris répétés.
app_event = Table(
    "app_event",
    metadata,
    Column("seq", BigInteger, primary_key=True, autoincrement=True),
    Column("event_id", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("workspace", Text, nullable=True),
    Column("subject", JSONB, nullable=False, server_default="{}"),
    Column("correlation_id", Text, nullable=True),
    Column("dedup_key", Text, nullable=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("consumed_by", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("idx_app_event_type", "event_type"),
    Index("idx_app_event_workspace", "workspace"),
)


# ─── Automates (port docflow, epic Termix T3) ─────────────────────────────────
#
# Contrats OpenAPI stockés globalement (réutilisables) : décrivent les opérations
# appelables. Un automate consomme le journal `app_event` par curseur et, pour un
# event retenu, résout puis appelle une opération d'un contrat.

openapi_contract = Table(
    "openapi_contract",
    metadata,
    Column("id", Text, primary_key=True),
    Column("label", Text, nullable=False),
    # Catégorie libre pour trier/regrouper les contrats dans l'IHM (vide = « Sans catégorie »).
    Column("category", Text, nullable=False, server_default=""),
    Column("source_url", Text, nullable=True),  # null = import manuel (pas de refresh)
    Column("version", Text, nullable=False, server_default=""),  # info.version (affichage)
    Column("raw_spec", JSONB, nullable=False),  # contrat OpenAPI complet
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Un automate = « sur tel(s) event(s), appelle telle opération d'un contrat ».
# `position` = ordre d'évaluation global (drag&drop) ; `stop_chain` = chaîne de
# responsabilité (match + appel OK → event consommé, priorités inférieures bloquées).
# Créé désactivé (`active=false`). `delay_minutes` = débounce en fenêtre glissante.
automation = Table(
    "automation",
    metadata,
    Column("id", Text, primary_key=True),
    Column("label", Text, nullable=False),
    # Identifiant lisible et stable côté IHM (prérempli du label normalisé).
    Column("slug", Text, nullable=False, server_default=""),
    Column("active", Boolean, nullable=False, server_default="false"),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("stop_chain", Boolean, nullable=False, server_default="false"),
    Column("event_types", ARRAY(Text), nullable=False, server_default="{}"),
    Column("delay_minutes", Integer, nullable=False, server_default="0"),
    Column(
        "contract_ref",
        Text,
        ForeignKey("openapi_contract.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("operation_id", Text, nullable=False),
    Column("url", Text, nullable=False),  # cible réelle (base du contrat + path résolu)
    Column("http_method", Text, nullable=False),
    Column("body_template", Text, nullable=True),  # modèle à variables ; null = pas de corps
    # Onglet Filtre : appel d'API préliminaire (évaluation différée) — tout nullable.
    Column(
        "filter_contract_ref",
        Text,
        ForeignKey("openapi_contract.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("filter_operation_id", Text, nullable=True),
    Column("filter_url", Text, nullable=True),
    Column("filter_method", Text, nullable=True),
    Column("filter_body", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("idx_automation_position", "position"),
    Index("uq_automation_slug", "slug", unique=True),
)

# Portée : les workspaces auxquels l'automate s'applique. `workspace = '*'` = tous.
# Jamais vide (au moins une portée). Un event de workspace W déclenche les automates
# de portée W ET ceux de portée '*'.
automation_scope = Table(
    "automation_scope",
    metadata,
    Column("automation_id", Text, ForeignKey("automation.id", ondelete="CASCADE"), nullable=False),
    Column("workspace", Text, nullable=False),
    UniqueConstraint("automation_id", "workspace", name="uq_automation_scope"),
)

# En-têtes d'appel : `value` XOR `secret_ref` (référence vault résolue à l'exécution).
automation_header = Table(
    "automation_header",
    metadata,
    Column("id", Text, primary_key=True),
    Column("automation_id", Text, ForeignKey("automation.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("value", Text, nullable=True),
    Column("secret_ref", Text, nullable=True),
    # Préfixe de valeur concaténé devant le secret résolu (ex. « Bearer »).
    Column("value_prefix", Text, nullable=False, server_default=""),
    # required : en-tête d'auth obligatoire (dérivé du contrat) ; enabled : ligne active.
    Column("required", Boolean, nullable=False, server_default="false"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Index("idx_automation_header_by_automation", "automation_id"),
)

# Curseur de progression sur `app_event.seq` (anti-rejeu, reprise sans perte).
automation_cursor = Table(
    "automation_cursor",
    metadata,
    Column(
        "automation_id",
        Text,
        ForeignKey("automation.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("last_seq", BigInteger, nullable=False, server_default="0"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Trace d'exécution (historique borné + rejeu). Anti-rejeu : index unique partiel
# (automation_id, dedup_key) sur les runs AUTOMATIQUES uniquement (manual=false) —
# un automate ne s'exécute qu'une fois par version ; un rejeu manuel est toujours
# autorisé (n'entre pas dans l'unicité).
automation_run = Table(
    "automation_run",
    metadata,
    Column("id", Text, primary_key=True),
    Column("automation_id", Text, ForeignKey("automation.id", ondelete="CASCADE"), nullable=False),
    Column("event_seq", BigInteger, nullable=False),
    Column("dedup_key", Text, nullable=False),
    Column("status", Text, nullable=False),  # ok | failed | skipped
    Column("http_status", Integer, nullable=True),
    Column("request_preview", Text, nullable=True),
    Column("response_preview", Text, nullable=True),
    Column("error", Text, nullable=True),
    Column("manual", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index(
        "uq_automation_run_auto_dedup",
        "automation_id",
        "dedup_key",
        unique=True,
        postgresql_where=text("manual = false"),
    ),
    Index("idx_automation_run_history", "automation_id", "created_at"),
)


# Préférences UI par utilisateur (clé fonctionnelle composée → valeur typée).
# Une ligne = (login, pref_key) ; la valeur est rangée dans la colonne du type
# indiqué par `value_type` (les deux autres colonnes restent NULL). Évite de
# multiplier les colonnes sur `users` pour chaque réglage d'interface.
user_preferences = Table(
    "user_preferences",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("pref_key", Text, nullable=False),
    Column("value_type", Text, nullable=False),
    Column("value_int", Integer, nullable=True),
    Column("value_text", Text, nullable=True),
    Column("value_bool", Boolean, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "value_type IN ('int', 'string', 'bool')", name="ck_user_preferences_value_type"
    ),
    UniqueConstraint("login", "pref_key", name="uq_user_preferences_login_key"),
)


# Kiosque d'applications : liens partagés (icône + nom + URL) affichés sur la
# page /applications pour TOUS les utilisateurs. Gérés exclusivement par un
# admin ; l'icône est libre : emoji/texte court ou URL d'image https.
kiosk_applications = Table(
    "kiosk_applications",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False, unique=True),
    Column("url", Text, nullable=False),
    Column("icon", Text, nullable=False, server_default=""),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


# Registre des skills (skills.sh) — DEUX cycles de vie distincts liés par FK,
# à ne JAMAIS fusionner (spec epic skills) :
# - skill_grants : AUTORISATION per-user, human-gated. Keyée user_subject (sub
#   OIDC) — v1 single-principal, mais le subject rouvre le multi-principal sans
#   réécriture. requested → pending → granted → (revoked | paused). Le grant
#   porte sur (user, skill, approved_hash) : une dérive de hash retombe en
#   pending SANS effacer approved_hash (comparaison à la re-validation).
# - skill_placements : INSTALLATION per-workspace. requested → placed →
#   verified | unverified. installed_hash figé à l'installation (pas de check
#   continu).
# INVARIANT de cascade : révoquer/pauser un grant coupe le routage de tous ses
# placements — appliqué par la requête d'ensemble effectif (JOIN sur le statut
# du grant), les lignes placements restent en base pour l'audit.
skill_grants = Table(
    "skill_grants",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_subject", Text, nullable=False),
    Column("skill_id", Text, nullable=False),
    Column("approved_hash", Text, nullable=True),
    Column("statut", Text, nullable=False, server_default="pending"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("granted_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "statut IN ('requested', 'pending', 'granted', 'paused', 'revoked')",
        name="ck_skill_grants_statut",
    ),
    UniqueConstraint("user_subject", "skill_id", name="uq_skill_grants_subject_skill"),
)


skill_placements = Table(
    "skill_placements",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "grant_id",
        BigInteger,
        ForeignKey("skill_grants.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("workspace_id", Text, nullable=False),
    Column("installed_hash", Text, nullable=True),
    Column("statut", Text, nullable=False, server_default="requested"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "statut IN ('requested', 'placed', 'verified', 'unverified')",
        name="ck_skill_placements_statut",
    ),
    UniqueConstraint("grant_id", "workspace_id", name="uq_skill_placements_grant_ws"),
)


# Délégation agent↔humain : l'agent est un acteur on-behalf-of, JAMAIS un
# principal autonome (epic skills). L'autorisation résout l'agent vers son
# principal délégant ; grants effectifs de l'agent = grants du principal,
# jamais davantage. Révoquer la délégation = kill-switch indépendant des
# grants. Source de vérité remplaçable plus tard par un token exchange
# Keycloak sans changer la logique d'autorisation. Une seule délégation
# ACTIVE par (agent_id, scope) — index unique partiel (revoked_at IS NULL)
# posé par la migration 067 : une révoquée reste en base pour l'audit.
agent_delegations = Table(
    "agent_delegations",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("agent_id", Text, nullable=False),
    Column("principal_subject", Text, nullable=False),
    Column("scope", Text, nullable=False, server_default="skills"),
    Column("granted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
)


# Sources de découverte MCP : une instance mcp-manager (URL de base) + une
# référence (slug) vers un secret utilisateur de type MCP_DISCOVERY. On y
# recherche des services MCP pour les ajouter ensuite comme serveurs.
mcp_discovery_source = Table(
    "mcp_discovery_source",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("label", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("secret_slug", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("login", "slug", name="uq_mcp_discovery_source_login_slug"),
)
