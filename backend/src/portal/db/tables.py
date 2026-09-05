from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
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
    # TSDB des metriques machine (endpoint remote_write) — migration 108.
    Column("logs_metrics_push_url", Text, nullable=False, server_default=""),
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
    # EventsProducerConfig (relais d'events signé HMAC vers le module workflow), migration 093.
    Column("events_enabled", Boolean, nullable=False, server_default="false"),
    Column("events_workflow_base_url", Text, nullable=False, server_default=""),
    Column("events_source_id", Text, nullable=False, server_default=""),
    Column("events_secret_slug", Text, nullable=False, server_default="workflow_events_hmac"),
    Column("events_source_uri", Text, nullable=False, server_default="urn:yoops:devpod"),
    Column("events_types", ARRAY(Text), nullable=False, server_default="{}"),
    # BastionConfig (sshd bastion + provisioning Termix), migration 093.
    Column("bastion_enabled", Boolean, nullable=False, server_default="false"),
    Column("bastion_api_url", Text, nullable=False, server_default=""),
    Column("bastion_host", Text, nullable=False, server_default=""),
    Column("bastion_port", Integer, nullable=False, server_default="2222"),
    Column("bastion_role", Text, nullable=False, server_default=""),
    Column("bastion_apikey_secret", Text, nullable=False, server_default="termix-apikey"),
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
    # Actions et variables declarees par le type (migration 122). Elles ne
    # vivaient qu'en memoire : servies par le cache de la config globale, elles
    # disparaissaient au premier rechargement depuis la base.
    Column("actions", JSONB, nullable=False, server_default="[]"),
    Column("variables", JSONB, nullable=False, server_default="[]"),
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
    # Profil avec lequel la machine a ete montee : provenance, pas contrainte.
    Column("profile_slug", Text, nullable=False, server_default=""),
    # Capacite PHYSIQUE : combien de workspaces la machine tient sans planter.
    # Elle vit ici et non sur la propriete — une machine mutualisee n'a pas de
    # proprietaire, et une machine enrolee a la main n'a pas de profil.
    # NULL = non renseigne : ni zero, ni illimite.
    Column("capacity_workspaces", Integer, nullable=True),
    # Ouverture au pool mutualise, acte delibere de l'exploitant.
    Column("accepts_mutualise", Boolean, nullable=False, server_default="false"),
    # Hyperviseur qui a monte la machine : PROVENANCE, pas contrainte — comme
    # `profile_slug`. Pas de cle etrangere : supprimer un hyperviseur ne doit ni
    # effacer des machines ni bloquer l'operation. Vide = provenance inconnue
    # (enrolee a la main), et surtout pas un hyperviseur par defaut.
    Column("hypervisor", Text, nullable=False, server_default=""),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "capacity_workspaces IS NULL OR capacity_workspaces >= 0", name="ck_host_capacity"
    ),
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
    # Rôle admin (claim OIDC) persisté à chaque login → permet de pousser aux admins
    # (hosts d'infra, serveurs de ressources) hors contexte de requête. Migration 101.
    Column("is_admin", Boolean, nullable=False, server_default="false"),
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
    # Portée MACHINE de la recette (workspace | host) et familles visées.
    # `host_scope` et non `scope` : la colonne `scope` ci-dessus désigne la
    # portée du CATALOGUE (partagé / propre à un utilisateur), tout autre chose.
    Column("host_scope", Text, nullable=False, server_default="workspace"),
    Column("host_usages", ARRAY(Text), nullable=False, server_default="{}"),
    Column("preconditions", JSONB, nullable=False, server_default="[]"),
    # URL du manifeste distant d'ou la recette a ete importee — migration 109.
    # Vide pour une recette creee a la main ou livree avec le produit.
    Column("source_url", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# ─── Profils de machine (remplacent test_host_params) ────────────────────────

machine_profiles = Table(
    "machine_profiles",
    metadata,
    Column("slug", Text, primary_key=True),
    Column("label", Text, nullable=False),
    # `ressources` est stocke mais pas encore exploite a la creation.
    Column("machine_type", Text, nullable=False, server_default="test"),
    # Obligatoire : les params sont types par la spec du script de ce type.
    Column("hypervisor_type", Text, nullable=False),
    Column("params", JSONB, nullable=False, server_default="{}"),
    # [{key, options}] — l'ORDRE compte, d'ou un tableau JSON.
    Column("recipes", JSONB, nullable=False, server_default="[]"),
    # [{template_id, deployment_id, params}] — services lances au demarrage.
    Column("services", JSONB, nullable=False, server_default="[]"),
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
    # Port SSH par workspace publié sur l'IP du node (spec 18 T1), plage 50000-59999.
    Column("ssh_port", Integer, nullable=True),
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

# Disque, mémoire et charge CPU des hosts (migrations 102/103) : posés par la sonde
# (nodes/metrics.py), lue par node_list et l'agrégat sessions. Un host jamais sondé
# n'a PAS de ligne — l'absence se lit « inconnu », JAMAIS « 0 % » : afficher un
# disque vide alors qu'on n'en sait rien est pire que de ne rien afficher.
# `error` retient la raison du dernier échec pour que l'UI puisse l'expliquer.
host_disk = Table(
    "host_disk",
    metadata,
    Column("name", Text, primary_key=True),
    Column("total_bytes", BigInteger, nullable=True),
    Column("used_bytes", BigInteger, nullable=True),
    Column("avail_bytes", BigInteger, nullable=True),
    Column("used_pct", Integer, nullable=True),
    # Mémoire et charge CPU relevées par la MÊME sonde (une seule connexion SSH).
    # « Utilisé » mémoire = total − MemAvailable (le cache est récupérable).
    # cpu_pct = charge 1 min ramenée au nombre de cœurs : 100 % = cœurs saturés.
    Column("mem_total_bytes", BigInteger, nullable=True),
    Column("mem_used_bytes", BigInteger, nullable=True),
    Column("mem_pct", Integer, nullable=True),
    Column("cpu_pct", Integer, nullable=True),
    Column("cpu_cores", Integer, nullable=True),
    # Une date PAR famille (migration 103) : les trois cadences diffèrent
    # (1 h / 5 min / 30 s), un horodatage unique ferait passer un disque vieux
    # d'une heure pour aussi frais qu'un CPU de 30 s.
    Column("disk_measured_at", DateTime(timezone=True), nullable=True),
    Column("mem_measured_at", DateTime(timezone=True), nullable=True),
    Column("cpu_measured_at", DateTime(timezone=True), nullable=True),
    Column("error", Text, nullable=True),
    # Date de la dernière sonde, quelle qu'elle soit (diagnostic).
    Column("measured_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
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

# Registre d'instances Termix (spec 18 T2) : une instance = un serveur Termix
# (URL + apikey admin en secret système). Un user est rattaché à une instance ;
# `is_default` désigne l'instance héritée par défaut (au plus une à True).
termix_instance = Table(
    "termix_instance",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False, unique=True),
    Column("url", Text, nullable=False),
    # Slug du secret système portant l'apikey admin `tmx_` de cette instance.
    Column("apikey_secret", Text, nullable=False),
    # client_id OIDC Keycloak de l'instance (référence/affichage ; l'OIDC est
    # configuré côté Termix, le portail n'en a pas besoin pour provisionner).
    Column("oidc_client_id", Text, nullable=False, server_default=""),
    Column("is_default", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Rattachement user→instances Termix (spec 18 T4b). N-N plafonnée à 3 côté appli
# (fallback/migration) : un user peut être servi par jusqu'à 3 serveurs Termix,
# le provisioning fan-out réplique ses hosts sur chacun. Vide = héritage de
# l'instance `is_default`. CASCADE des deux côtés.
user_termix_instance = Table(
    "user_termix_instance",
    metadata,
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), primary_key=True),
    Column(
        "instance_id",
        Text,
        ForeignKey("termix_instance.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Portée user→host SSH (spec 18 T3). N-N pure : quel user a accès à quel host
# Termix (= un workspace SSH publié, identifié par `ws_id`). Consulté par le
# provisioning (T5) pour partager le host aux seuls users accordés, et par le
# sélecteur de host de la page Utilisateurs (T4). PK composite (login, ws_id) ;
# CASCADE des deux côtés (suppression user ou workspace ⇒ grants effacés).
user_host_grant = Table(
    "user_host_grant",
    metadata,
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), primary_key=True),
    Column(
        "ws_id",
        Text,
        ForeignKey("workspace_status.ws_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Un automate = « sur tel(s) event(s), exécute l'arbre de règle `tree` ».
# `position` = ordre d'évaluation global (drag&drop) ; `stop_chain` = chaîne de
# responsabilité (match + exécution OK → event consommé, priorités inférieures
# bloquées). Créé désactivé (`active=false`). `delay_minutes` = débounce en
# fenêtre glissante. `tree` (migration 094) = blocs récursifs {filtre ET/OU
# imbriqué → appels nommés → blocs enfants}, schéma automations/tree.py.
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
    Column("tree", JSONB, nullable=False, server_default='{"version": 1, "blocks": []}'),
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

# Les en-têtes d'appel vivent désormais DANS l'arbre (`automation.tree`), par
# appel/filtre (migration 095) — plus de table `automation_header`.

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
    # Trace structurée du parcours de l'arbre (un item par nœud exécuté), migration 094.
    Column("trace", JSONB, nullable=True),
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


# ─── Forfaits : pays, fiscalité, catalogue d'offres ───────────────────────────
#
# Périmètre initial : la France seule (cadrage du 27/08). Les États-Unis
# reviendront en `tax_mode = automatique` — le modèle les porte déjà, aucune
# migration à prévoir pour ça.

# Pays où la plateforme opère. Le pays RÉFÉRENCE ses providers (un provider peut
# servir plusieurs pays), et porte ses devises.
countries = Table(
    "countries",
    metadata,
    Column("code", Text, primary_key=True),  # ISO-3166-1 alpha-2, majuscules
    Column("label", Text, nullable=False),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Devises acceptées dans un pays. `is_default` désigne celle proposée par défaut ;
# un index partiel unique garantit qu'il n'y en a qu'une par pays — deux défauts
# rendraient le choix de devise non déterministe au moment de proposer une offre.
# Devises acceptees par l'application. Jeu GLOBAL : ce que la plateforme sait
# encaisser ne depend pas du pays de l'acheteur. L'index partiel garantit
# qu'exactement une devise porte le defaut — deux rendraient le choix
# indetermine au moment de presenter un prix.
currencies = Table(
    "currencies",
    metadata,
    Column("code", Text, primary_key=True),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("is_default", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index(
    "uq_currency_default",
    currencies.c.is_default,
    unique=True,
    postgresql_where=text("is_default"),
)

# Canal de paiement. `kind` est le DISCRIMINANT d'adaptateur, `slug` identifie
# l'INSTANCE : deux comptes Stripe (test et production, ou deux entités
# juridiques) doivent coexister sans dupliquer le code de l'adaptateur.
#
# Aucun secret ici : `secret_slug` référence la table des secrets, jamais la clé
# elle-même. `config` porte le non-secret propre au `kind`, validé à l'écriture
# par un modèle pydantic — JSONB pour ne pas faire une table à trous, validé
# pour ne pas en faire un sac fourre-tout.
payment_providers = Table(
    "payment_providers",
    metadata,
    Column("slug", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("label", Text, nullable=False),
    # `automatique` = on envoie du HT, le provider calcule la taxe.
    # `manuel` = on calcule la taxe et on envoie du TTC.
    Column("tax_mode", Text, nullable=False, server_default="manuel"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("config", JSONB, nullable=False, server_default="{}"),
    Column("secret_slug", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("tax_mode IN ('automatique','manuel')", name="ck_provider_tax_mode"),
)

# Providers utilisables dans un pays, par ordre de priorité croissante.
country_providers = Table(
    "country_providers",
    metadata,
    Column("country_code", Text, ForeignKey("countries.code", ondelete="CASCADE"), nullable=False),
    Column(
        "provider_slug",
        Text,
        ForeignKey("payment_providers.slug", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("priority", Integer, nullable=False, server_default="0"),
    UniqueConstraint("country_code", "provider_slug", name="uq_country_provider"),
)

# Taux de taxe, en mode `manuel` uniquement.
#
# HISTORISÉ, jamais écrasé : une facture émise l'an dernier doit rester
# reproductible avec le taux de l'époque. Le calcul retient le taux dont la
# période couvre la DATE D'ÉMISSION, pas le taux courant.
#
# `region` vide = tout le pays. Conservée dès maintenant pour un futur pays à
# taux régionaux : la colonne ne coûte rien, la migration coûterait.
tax_rates = Table(
    "tax_rates",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("country_code", Text, ForeignKey("countries.code", ondelete="CASCADE"), nullable=False),
    Column("region", Text, nullable=False, server_default=""),
    # NUMERIC et non float : 0.2000 = 20 %. L'exactitude prime sur la commodité.
    Column("rate", Numeric(7, 4), nullable=False),
    Column("label", Text, nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date, nullable=True),  # NULL = en vigueur
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("rate >= 0", name="ck_tax_rate_positive"),
    CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_tax_rate_period"),
)
Index("ix_tax_rates_lookup", tax_rates.c.country_code, tax_rates.c.region, tax_rates.c.valid_from)

# Offre d'abonnement. Les libellés sont i18n (JSONB {langue: texte}).
offers = Table(
    "offers",
    metadata,
    Column("slug", Text, primary_key=True),
    # Nom court non traduit (« Standard »), pour l'administration et les
    # journaux. Le titre montre au client, lui, est traduit.
    Column("label", Text, nullable=False, server_default=""),
    Column("titles", JSONB, nullable=False, server_default="{}"),
    Column("descriptions", JSONB, nullable=False, server_default="{}"),
    Column("hosting_type", Text, nullable=False, server_default="mutualise"),
    # NULL = illimité, pour les deux. Deux quotas indépendants.
    Column("max_workspaces", Integer, nullable=True),
    Column("max_hosts_dedies", Integer, nullable=True),
    # Variables libres de l'offre (gabarit VM, capacité du host…), injectées
    # dans les événements debut_essai / activation.
    Column("variables", JSONB, nullable=False, server_default="{}"),
    Column("provider_slug", Text, ForeignKey("payment_providers.slug"), nullable=True),
    # Une offre non publiée n'est proposée à personne : c'est l'état d'une offre
    # en cours de saisie, et celui d'une offre retirée du catalogue.
    Column("published", Boolean, nullable=False, server_default="false"),
    # Sens du montant saisi : TTC (true) ou HT (false). Explicite plutot que
    # deduit du mode de taxe du canal — une offre peut changer de canal sans que
    # ses prix changent de nature.
    Column("prices_include_tax", Boolean, nullable=False, server_default="false"),
    # Devises acceptees sans prix propre : derivees du prix par defaut. La
    # majoration n'est PAS un taux de change, c'est une majoration commerciale.
    Column("auto_currencies", Boolean, nullable=False, server_default="false"),
    Column("currency_markup", Numeric(7, 4), nullable=False, server_default="1"),
    # Offre gratuite : forfait de bienvenue, sans aucun prix. Un drapeau et non
    # l'absence de tarif — une offre payante dont on a oublie le prix est une
    # erreur de saisie, pas une offre gratuite.
    Column("is_free", Boolean, nullable=False, server_default="false"),
    # Duree du forfait EN JOURS. Tout forfait est borne, gratuit comme payant.
    # NULL = pas encore renseignee : l'offre reste un brouillon, la publication
    # l'exige.
    Column("duration_days", Integer, nullable=True),
    # Au terme, le forfait repart-il ? Faux par defaut : reconduire d'office
    # prelegerait quelqu'un qui n'a rien demande.
    Column("tacite_reconduction", Boolean, nullable=False, server_default="false"),
    # Ce forfait peut-il etre repris par le meme compte ? Faux par defaut, donc
    # repetable : prendre deux fois le meme forfait payant est legitime. Un
    # PARAMETRE et non une exception sur `is_free` — c'est une decision
    # commerciale, pas une propriete de la gratuite.
    Column("une_par_compte", Boolean, nullable=False, server_default="false"),
    # Ordre d'affichage decide par l'administrateur, croissant : 0 en premier.
    # Le tri par slug etait alphabetique, donc arbitraire commercialement.
    # A priorite egale, `slug` departage — un tri instable ferait bouger le
    # catalogue d'un rechargement a l'autre.
    Column("priorite", Integer, nullable=False, server_default="100"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("hosting_type IN ('dedie','mutualise')", name="ck_offer_hosting_type"),
    CheckConstraint("priorite >= 0", name="ck_offer_priorite"),
    CheckConstraint("duration_days IS NULL OR duration_days > 0", name="ck_offer_duration"),
    CheckConstraint("currency_markup > 0", name="ck_offer_markup"),
    CheckConstraint("max_workspaces IS NULL OR max_workspaces > 0", name="ck_offer_max_ws"),
    CheckConstraint("max_hosts_dedies IS NULL OR max_hosts_dedies > 0", name="ck_offer_max_hosts"),
)

# Profils de host qu'une offre sait provisionner, et dans quel ordre.
#
# `priorite` porte le rang (0 = essayé en premier) : une table SQL n'a pas
# d'ordre propre, et sans rang la liste reviendrait mélangée à chaque relecture.
# Le rang est réécrit en bloc à chaque enregistrement, comme les prix — le corps
# reçu décrit l'état voulu, pas un delta.
#
# FK RESTRICT vers `host_profiles` : supprimer un profil référencé par une offre
# rendrait cette offre improvisionnable en silence. La route le refuse en 409 et
# nomme les offres concernées, comme elle refuse déjà de supprimer une offre
# souscrite.
offer_host_profiles = Table(
    "offer_host_profiles",
    metadata,
    Column("offer_slug", Text, ForeignKey("offers.slug", ondelete="CASCADE"), nullable=False),
    Column(
        "profile_slug",
        Text,
        ForeignKey("host_profiles.slug", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("priorite", Integer, nullable=False),
    UniqueConstraint("offer_slug", "profile_slug", name="uq_offer_host_profile"),
    CheckConstraint("priorite >= 0", name="ck_offer_host_profile_priorite"),
)
Index("ix_offer_host_profiles_profile", offer_host_profiles.c.profile_slug)


# Prix d'une offre, PAR DEVISE. Montant en unités mineures (centimes) : entier,
# jamais un flottant — c'est la règle de la facturation et celle de l'API Stripe.
#
# Le sens du montant dépend du `tax_mode` du provider : HT en `automatique`
# (le provider ajoute la taxe), TTC en `manuel` (on l'a déjà calculée).
offer_prices = Table(
    "offer_prices",
    metadata,
    Column("offer_slug", Text, ForeignKey("offers.slug", ondelete="CASCADE"), nullable=False),
    Column("currency", Text, nullable=False),
    Column("amount_minor", BigInteger, nullable=False),
    # Identifiant du prix côté fournisseur (price_id Stripe…), posé à la
    # synchronisation. Vide tant que l'offre n'a pas été poussée au provider.
    Column("provider_price_id", Text, nullable=False, server_default=""),
    UniqueConstraint("offer_slug", "currency", name="uq_offer_price_currency"),
    CheckConstraint("amount_minor >= 0", name="ck_offer_price_positive"),
)


# ─── Forfaits : abonnements et propriété des machines ────────────────────────

# Abonnement d'un utilisateur à une offre.
#
# `currency` et `amount_minor` sont un INSTANTANÉ du prix au moment de la
# souscription, pas une lecture de `offer_prices` : le catalogue évolue, un
# abonné garde le prix auquel il a souscrit. C'est aussi ce qui permet de
# rejouer une facture ancienne.
subscriptions = Table(
    "subscriptions",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("offer_slug", Text, ForeignKey("offers.slug"), nullable=False),
    Column("provider_slug", Text, ForeignKey("payment_providers.slug"), nullable=True),
    # `resilie` est un état CLOS, pas définitif : l'abonnement s'arrête, le
    # compte demeure, et une reprise le rouvre (au tarif du jour). Le seul acte
    # définitif est la suppression du compte, qui efface la ligne `users` et
    # emporte celle-ci en CASCADE — ce n'est pas un état d'abonnement.
    Column("state", Text, nullable=False, server_default="essai"),
    Column("country_code", Text, nullable=False),
    Column("currency", Text, nullable=False),
    Column("amount_minor", BigInteger, nullable=False),
    # Identifiant de l'abonnement côté fournisseur (`sub_…`).
    Column("provider_subscription_id", Text, nullable=False, server_default=""),
    # Echecs de prelevement CONSECUTIFS de l'episode en cours, remis a zero des
    # qu'un paiement passe. `next_retry_at` porte la relance programmee : on ne
    # coupe pas au premier refus (souvent passager), on relance une fois puis on
    # resilie — de facon reversible.
    Column("payment_attempts", Integer, nullable=False, server_default="0"),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("trial_end", DateTime(timezone=True), nullable=True),
    Column("current_period_end", DateTime(timezone=True), nullable=True),
    # Jour d'arret du forfait, calcule a la souscription depuis la duree de
    # l'offre. Distinct de `current_period_end`, qui est la fin de la PERIODE
    # facturee cote fournisseur : celle-ci se renouvelle, le terme arrete le
    # service.
    Column("ends_at", DateTime(timezone=True), nullable=True),
    # Adresse de facturation FIGEE a la souscription (blob chiffre serveur,
    # migration 129) : celle qui a servi, elle ne bouge plus — meme doctrine
    # que l'instantane de prix. NULL = souscription sans adresse au profil.
    Column("billing_address_enc", LargeBinary, nullable=True),
    # Date du dernier changement d'état : c'est d'elle que le scheduler déduit
    # l'échéance de rétention, en y ajoutant le délai configuré pour l'événement.
    Column("state_changed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "state IN ('essai','actif','echec_paiement','resilie')", name="ck_subscription_state"
    ),
    CheckConstraint("amount_minor >= 0", name="ck_subscription_amount"),
    CheckConstraint("payment_attempts >= 0", name="ck_subscription_attempts"),
)
Index("ix_subscriptions_login", subscriptions.c.login)
Index("ix_subscriptions_state", subscriptions.c.state, subscriptions.c.state_changed_at)
# Le scheduler de relance demande « qui est du maintenant ? » : index partiel,
# pour ne pas balayer les abonnements sains a chaque tick.
Index(
    "ix_subscriptions_retry",
    subscriptions.c.next_retry_at,
    postgresql_where=subscriptions.c.next_retry_at.isnot(None),
)

# Historique des événements d'abonnement, ET magasin d'idempotence des webhooks.
#
# `(provider_slug, provider_event_id)` est UNIQUE : chaque webhook porte un id
# d'événement, un événement déjà vu est ignoré en silence. Sans cette
# contrainte, un renvoi du fournisseur — cas normal, ils réessaient — pourrait
# provisionner deux fois ou facturer deux fois.
subscription_events = Table(
    "subscription_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "subscription_id",
        UUID(as_uuid=False),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column("login", Text, nullable=False, server_default=""),
    Column("kind", Text, nullable=False),
    Column("provider_slug", Text, nullable=False),
    Column("provider_event_id", Text, nullable=False),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    # Visibilite de l'entree (migration 127) : `achat` = le compte en tant que
    # client, servie a l'utilisateur ; `operation` = geste d'exploitation,
    # reservee aux ecrans admin. UNE source, trois points d'acces — le filtre
    # est porte par l'entree, pas par trois requetes divergentes.
    Column("visibilite", Text, nullable=False, server_default="achat"),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("provider_slug", "provider_event_id", name="uq_subscription_event_provider"),
    CheckConstraint(
        "kind IN ('debut_essai','activation','renouvellement','echec_paiement','resiliation',"
        "'remboursement','litige_ouvert','litige_clos')",
        name="ck_subscription_event_kind",
    ),
    CheckConstraint(
        "visibilite IN ('achat','operation')", name="ck_subscription_event_visibilite"
    ),
)

# Adresse de facturation COURANTE du compte (migration 129) : un blob chiffre
# cote serveur (KEK + HKDF domaine dedie, pas le coffre a PIN — le
# renouvellement doit la relire sans l'utilisateur). Aucune colonne en clair.
billing_addresses = Table(
    "billing_addresses",
    metadata,
    Column("login", Text, ForeignKey("users.login", ondelete="CASCADE"), primary_key=True),
    Column("adresse_enc", LargeBinary, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Trace des expirations de rétention notifiées (migration 128).
#
# L'épisode `(subscription_id, state, state_changed_at)` est UNIQUE : le
# scheduler émet `subscription.retention_expired` UNE fois par épisode — c'est
# la seule règle du lot qui mène à détruire des données, un double
# déclenchement est exactement le défaut que la fiche interdit. Un abonnement
# retombé en échec après s'être rétabli a un nouveau `state_changed_at` : c'est
# un nouvel épisode, notifié à son tour.
retention_notifications = Table(
    "retention_notifications",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "subscription_id",
        UUID(as_uuid=False),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("state", Text, nullable=False),
    Column("state_changed_at", DateTime(timezone=True), nullable=False),
    Column("emitted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "subscription_id", "state", "state_changed_at", name="uq_retention_notification_episode"
    ),
    CheckConstraint(
        "state IN ('echec_paiement','resilie')", name="ck_retention_notification_state"
    ),
)
Index("ix_subscription_events_sub", subscription_events.c.subscription_id)

# Propriété d'une machine par un utilisateur (hébergement `dedie`).
#
# Deux plafonds distincts, et leur ordre n'est pas negociable :
#   1. `capacity_workspaces` = ce que la MACHINE supporte, le nombre de
#      workspaces qui peuvent y tourner sans la faire planter. Limite physique,
#      elle prime sur tout — aucun forfait ne fait acheter de la RAM.
#   2. `offer_max_workspaces` = le quota du forfait au provisionnement. Il peut
#      etre plus bas que la capacite, jamais la relever.
# C'est une capacite de MACHINE, partagee entre l'owner et ses invites, pas un
# quota individuel toutes machines confondues.
host_ownership = Table(
    "host_ownership",
    metadata,
    Column("host_name", Text, ForeignKey("hosts.name", ondelete="CASCADE"), primary_key=True),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("hosting_type", Text, nullable=False, server_default="dedie"),
    Column("offer_slug", Text, nullable=True),
    # La capacite d'accueil N'EST PAS ici : c'est un fait de la MACHINE, il vit
    # sur `hosts.capacity_workspaces` depuis la migration 117. La recopier sur
    # la propriete creait une seconde verite (migration 125).
    #
    # `offer_max_workspaces` reste : quota du forfait fige au provisionnement,
    # donnee commerciale, qui n'a aucune raison de vivre sur la machine.
    # NULL = pas de plafond de ce cote-la.
    Column("offer_max_workspaces", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("hosting_type IN ('dedie','mutualise')", name="ck_ownership_hosting_type"),
)
Index("ix_host_ownership_owner", host_ownership.c.owner_login)

# Ce qu'un ABONNEMENT a obtenu, machine par machine.
#
# Une ligne = « cet abonnement dispose de tant de workspaces sur cette
# machine ». Les deux cas du catalogue ne different que par la presence d'une
# part :
#   - `allocated_workspaces` NULL  -> machine DEDIEE. Le forfait limite le
#     NOMBRE DE MACHINES, pas les workspaces : seule la capacite physique de la
#     machine borne ce qui tourne dessus.
#   - un entier                    -> part sur une machine MUTUALISEE. La somme
#     des parts d'un abonnement ne depasse pas le quota du forfait, et la somme
#     des parts posees sur une machine ne depasse pas sa capacite. Deux
#     invariants distincts : l'un commercial, l'autre physique.
#
# La cle primaire (abonnement, machine) porte l'idempotence : un webhook rejoue
# REMPLACE la part au lieu d'en ajouter une seconde.
subscription_hosts = Table(
    "subscription_hosts",
    metadata,
    Column(
        "subscription_id",
        UUID(as_uuid=False),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "host_name",
        Text,
        ForeignKey("hosts.name", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("allocated_workspaces", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "allocated_workspaces IS NULL OR allocated_workspaces > 0",
        name="ck_subscription_host_part",
    ),
)
Index("ix_subscription_hosts_host", subscription_hosts.c.host_name)

# Invités d'une machine dédiée : l'owner saisit un email, un lien d'invitation
# part. `login` reste NULL tant que l'invitation n'est pas acceptée — on invite
# une adresse, pas forcément un compte déjà existant.
host_guests = Table(
    "host_guests",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("host_name", Text, ForeignKey("hosts.name", ondelete="CASCADE"), nullable=False),
    Column("email", Text, nullable=False),
    Column("login", Text, ForeignKey("users.login", ondelete="SET NULL"), nullable=True),
    # Sous-limite de l'invité, dans la capacité du host. NULL = pas de
    # sous-limite : l'invité peut consommer la capacité restante.
    Column("allocated_workspaces", Integer, nullable=True),
    Column("state", Text, nullable=False, server_default="invite"),
    Column("token", Text, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("accepted_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("host_name", "email", name="uq_host_guest_email"),
    UniqueConstraint("token", name="uq_host_guest_token"),
    CheckConstraint("state IN ('invite','accepte','revoque')", name="ck_host_guest_state"),
    CheckConstraint(
        "allocated_workspaces IS NULL OR allocated_workspaces > 0", name="ck_host_guest_alloc"
    ),
)
Index("ix_host_guests_login", host_guests.c.login)


# Profil de host : ce qu'un forfait provisionne.
#
# Trois niveaux — le type d'hyperviseur DECLARE les variables, le profil de
# machine fige les parametres de creation, le profil de host VALUE les
# variables. `capacity_workspaces` y vit : le profil de machine sait construire
# la VM, il ne sait pas combien de workspaces elle tient sans planter. Seul
# l'exploitant le sait, et c'est ici qu'il le dit.
#
# Pas de cle etrangere vers `machine_profiles` : le portail valide l'existence
# du profil a l'enregistrement, et une reference devenue pendante reste lisible
# — savoir sur quel profil un host a ete monte garde sa valeur meme si ce profil
# a disparu (meme choix que `hosts.profile_slug`).
host_profiles = Table(
    "host_profiles",
    metadata,
    Column("slug", Text, primary_key=True),
    Column("label", Text, nullable=False),
    Column("machine_profile", Text, nullable=False),
    # {slug de variable: valeur}, en texte — la declaration porte le type.
    Column("variables", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("ix_host_profiles_machine", host_profiles.c.machine_profile)


# Trace des provisionings : ce qui a ete decide, et ce qui en est advenu.
#
# Un abonnement peut etre paye sans que l'acces existe — creation de VM en
# echec, pool injoignable, script en erreur. Sans registre, cet ecart est
# INVISIBLE : le client paie, personne ne le sait, et on l'apprend par une
# reclamation. Cette table rend l'echec listable.
#
# `uq_provisioning_run_event` porte l'idempotence : un webhook rejoue — la
# norme, pas l'exception — ne cree pas une seconde tentative.
provisioning_runs = Table(
    "provisioning_runs",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "subscription_id",
        UUID(as_uuid=False),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Vide = declenchement manuel depuis l'administration.
    Column("provider_event_id", Text, nullable=False, server_default=""),
    Column("kind", Text, nullable=False),
    Column("owner_login", Text, ForeignKey("users.login", ondelete="CASCADE"), nullable=False),
    Column("offer_slug", Text, nullable=False),
    # Verdict recopie tel quel : on doit pouvoir relire ce qui a ete decide
    # meme si la regle a change depuis.
    Column("action", Text, nullable=False),
    Column("host_name", Text, nullable=True),
    # Gabarit retenu, recopie du verdict. Les trois maillons sont conserves et
    # pas seulement le dernier : le jour ou l'on se demande pourquoi telle
    # machine a ete montee ainsi, la reponse doit se lire ici plutot que se
    # reconstituer depuis une configuration qui a change depuis. NULL pour les
    # actions qui ne montent rien.
    Column("host_profile", Text, nullable=True),
    Column("machine_profile", Text, nullable=True),
    Column("hypervisor", Text, nullable=True),
    Column("motif", Text, nullable=False, server_default=""),
    Column("state", Text, nullable=False, server_default="decide"),
    # Message du dernier echec. Jamais un secret : c'est une trace d'ecran.
    Column("erreur", Text, nullable=False, server_default=""),
    # Ce que le driver a laisse derriere lui : provider = type de driver,
    # provider_ref = reference OPAQUE (contrat ticket 4), posee des que la
    # machine existe — y compris sur echec_apres_creation. NULL = rien.
    Column("provider", Text, nullable=False, server_default=""),
    Column("provider_ref", JSONB, nullable=True),
    # Noeud vise par le verdict (cible.noeud) — necessaire au rejeu fidele.
    Column("noeud", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "action IN ('rien','assigner_host','creer_host_mutualise',"
        "'creer_vm_dediee','impossible')",
        name="ck_provisioning_action",
    ),
    # 'echec' = lignes anterieures a la migration 128 (issue inconnue faute de
    # taxonomie a l'epoque) ; le nouveau code ne l'ecrit plus.
    CheckConstraint(
        "state IN ('decide','en_cours','fait','echec',"
        "'echec_avant_creation','echec_apres_creation','indetermine')",
        name="ck_provisioning_state",
    ),
    UniqueConstraint("subscription_id", "provider_event_id", name="uq_provisioning_run_event"),
)
Index(
    "ix_provisioning_runs_echec",
    provisioning_runs.c.state,
    postgresql_where=text(
        "state IN ('echec','echec_avant_creation','echec_apres_creation','indetermine')"
    ),
)
