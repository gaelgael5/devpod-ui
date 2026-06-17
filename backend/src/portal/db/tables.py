from __future__ import annotations

from sqlalchemy import ARRAY, Boolean, Column, DateTime, ForeignKey, Integer, MetaData, Table, Text, func
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
    Column("key_path", Text, nullable=False, server_default=""),
    Column("public_key", Text, nullable=False, server_default=""),
    Column("proxmox_node", Text, nullable=False, server_default=""),
    Column("vmid", Text, nullable=False, server_default=""),
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
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

workspace_extra_sources = Table(
    "workspace_extra_sources",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("workspace_id", Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("position", Integer, nullable=False),
    Column("url", Text, nullable=False),
    Column("branch", Text, nullable=False, server_default=""),
    Column("git_credential", Text, nullable=False, server_default=""),
)
