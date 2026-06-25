from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
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
    # LogConfig
    Column("log_level", Text, nullable=False, server_default="info"),
    Column("log_format", Text, nullable=False, server_default="text"),
    Column("log_output", Text, nullable=False, server_default=""),
    # OidcConfig
    Column("oidc_issuer", Text, nullable=False),
    Column("oidc_client_id", Text, nullable=False),
    Column("oidc_client_secret", Text, nullable=False, server_default=""),
    Column("oidc_scopes", ARRAY(Text), nullable=False),
    Column("oidc_role_claim", Text, nullable=False, server_default="realm_access.roles"),
    Column("oidc_admin_role", Text, nullable=False, server_default="admin"),
    Column("oidc_user_role", Text, nullable=False, server_default="dev"),
    Column("oidc_username_claim", Text, nullable=False, server_default="preferred_username"),
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
    Column("password", Text, nullable=False, server_default=""),
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
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("login", "name", name="uq_workspaces_login_name"),
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
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "login", "workspace_name", "host_name", name="uq_wth_login_ws_host"
    ),
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
    Column("private_key_local", LargeBinary, nullable=True),   # AES-GCM, master_key
    Column("private_key_vault_ref", Text, nullable=True),       # ${vault://id:certificats/slug/private}
    Column("storage_type", Text, nullable=False),               # local | harpocrate
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
    Column("enabled", Boolean, nullable=False, server_default="true"),
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

mcp_apikey = Table(
    "mcp_apikey",
    metadata,
    Column("id", Text, primary_key=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("token_hash", Text, nullable=False),  # sha256 hex du token clair
    Column("label", Text, nullable=False, server_default=""),
    Column("revoked", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

mcp_apikey_grant = Table(
    "mcp_apikey_grant",
    metadata,
    Column("apikey_id", Text, ForeignKey("mcp_apikey.id", ondelete="CASCADE"), nullable=False),
    Column("backend_id", Text, ForeignKey("mcp_backend.id", ondelete="CASCADE"), nullable=False),
    # nullable : un grant vers un backend public (sans auth) n'a pas de clé.
    Column(
        "backend_key_id",
        Text,
        ForeignKey("mcp_backend_key.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column("expose_mode", Text, nullable=False, server_default="all"),  # all | allowlist | denylist
    Column("expose", JSONB, nullable=False, server_default="[]"),
    UniqueConstraint("apikey_id", "backend_id", name="uq_mcp_apikey_grant_apikey_backend"),
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
