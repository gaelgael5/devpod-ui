from __future__ import annotations

import re
import uuid
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from portal.profiles.models import Scope


class LogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["debug", "info", "warning", "error"] = "info"
    format: Literal["text", "json"] = "text"
    output: str = ""


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listen: str = "0.0.0.0:8080"
    base_domain: str
    external_url: str
    dev_mode: bool = False
    # En dev, l'URL publique (external_url) passe par Cloudflare qui bloque les
    # ports non-standard.  workspace_host permet de spécifier l'IP/hostname
    # direct de la VM pour les URLs de workspace (ex : "192.168.10.50").
    workspace_host: str = ""
    # Domaine DNS local (ex. "home.lan") ajouté au nom d'une machine de test pour
    # re-résoudre son IP DHCP. Vide → on résout le nom seul.
    local_domain: str = ""
    # Sous-domaine fixe pour le proxy VS Code (ex. "vs-dev.yoops.org"). Quand renseigné,
    # un seul sous-domaine sert tous les workspaces ; Caddy résout l'upstream par cookie/session.
    vs_proxy_domain: str = ""
    # Domaine du cookie de session (ex. "yoops.org"). Obligatoire quand portail et
    # workspaces VS Code n'ont qu'un ancêtre commun (dev.yoops.org + vs-dev.yoops.org).
    # Vide → base_domain est utilisé par défaut.
    cookie_domain: str = ""
    # Durées de session paramétrables depuis l'admin (secondes). 0 = hériter du défaut
    # (settings/env). session_max_age = idle GLISSANT du cookie ; session_absolute_max_age
    # = plafond absolu depuis le login (refresh des rôles). Cf. auth/rbac + app.py.
    session_max_age: int = 0
    session_absolute_max_age: int = 0
    log: LogConfig = Field(default_factory=LogConfig)


_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](-?[a-z0-9])*(\.[a-z0-9](-?[a-z0-9])*)*$", re.IGNORECASE
)


def validate_network(
    base_domain: str,
    external_url: str,
    workspace_host: str,
    vs_proxy_domain: str = "",
    cookie_domain: str = "",
) -> dict[str, str]:
    """Valide/normalise la config réseau saisie par l'admin.

    Le vide est autorisé (routage par sous-domaine désactivé). Si renseigné :
    base_domain/workspace_host/vs_proxy_domain doivent être un hôte valide,
    external_url une URL absolue http(s). Retourne les valeurs nettoyées.
    """
    bd = base_domain.strip()
    if bd and not _HOSTNAME_RE.fullmatch(bd):
        raise ValueError(f"base_domain invalide: {base_domain!r}")
    eu = external_url.strip().rstrip("/")
    if eu:
        parsed = urlparse(eu)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"external_url doit être une URL absolue http(s): {external_url!r}")
    wh = workspace_host.strip()
    if wh and not _HOSTNAME_RE.fullmatch(wh):
        raise ValueError(f"workspace_host invalide: {workspace_host!r}")
    vpd = vs_proxy_domain.strip()
    if vpd and not _HOSTNAME_RE.fullmatch(vpd):
        raise ValueError(f"vs_proxy_domain invalide: {vs_proxy_domain!r}")
    cd = cookie_domain.strip() if cookie_domain else ""
    if cd and not _HOSTNAME_RE.fullmatch(cd):
        raise ValueError(f"cookie_domain invalide: {cookie_domain!r}")
    return {
        "base_domain": bd,
        "external_url": eu,
        "workspace_host": wh,
        "vs_proxy_domain": vpd,
        "cookie_domain": cd,
    }


class OidcConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer: str
    client_id: str
    client_secret: str

    @field_validator("issuer", "client_id", "client_secret", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email", "roles"])
    role_claim: str = "realm_access.roles"
    admin_role: str = "admin"
    user_role: str = "dev"
    username_claim: str = "preferred_username"
    # Quand False : le login local break-glass (LOCAL_USER/.env) est désactivé,
    # même si LOCAL_USER/LOCAL_PASSWORD_HASH sont présents dans .env.
    allow_local_auth: bool = True


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oidc: OidcConfig


class HarpocrateGlobalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = ""
    api_key: str = ""
    base_path: str = "devpod"


class SecretsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["harpocrate", "inline"] = "inline"
    harpocrate: HarpocrateGlobalConfig = Field(default_factory=HarpocrateGlobalConfig)


# Format docker : entier + unité b/k/m/g optionnelle (ex. 4g, 512m). La casse
# est normalisée en minuscule avant validation.
_MEMORY_LIMIT_RE = re.compile(r"^[0-9]+[bkmg]?$")


def _validate_memory_limit(v: str) -> str:
    v = v.strip().lower()
    if v and not _MEMORY_LIMIT_RE.fullmatch(v):
        raise ValueError(
            f"memory limit {v!r} invalide — entier + unité optionnelle b/k/m/g (ex. 4g, 512m)"
        )
    return v


class DevpodDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ide: str = "openvscode"
    idle_timeout: str = "2h"
    dotfiles: str = ""
    # Limite mémoire par défaut des conteneurs workspace (enabler 59864c37) :
    # docker --memory, appliquée à la (re)construction du conteneur. "" = aucune
    # limite (le choix de la valeur est une décision d'exploitation).
    memory_limit: str = ""

    @field_validator("memory_limit")
    @classmethod
    def validate_memory_limit(cls, v: str) -> str:
        return _validate_memory_limit(v)


class DevpodConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binary: str = "/usr/local/bin/devpod"
    defaults: DevpodDefaults = Field(default_factory=DevpodDefaults)
    client_cert_path: str = "/data/certs/portal"


class HostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    default: bool = False
    type: Literal["docker-tls", "ssh"]
    docker_host: str = ""
    address: str = ""
    proxmox_node: str = ""
    vmid: str = ""
    # Références vers harpo_* (slugs)
    ci_password_secret_slug: str = ""
    host_cert_slug: str = ""
    # Certificat client mTLS (docker-tls) : slug d'une entrée tls-* du
    # gestionnaire de certificats. Vide = répertoire partagé (client_cert_path).
    docker_cert_slug: str = ""
    # Préférences de stockage des secrets
    storage_type: Literal["local", "harpocrate"] = "local"
    vault_identifier: str = ""
    # Destination du host : workspaces, tests, portail (machine du portail),
    # ressources (service partagé permanent, sans workspace propriétaire — spec 33),
    # ou autres (inventaire simple : ni workspaces, ni services compose).
    usage: Literal["workspaces", "tests", "portail", "ressources", "autres"] = "workspaces"


_PROXMOX_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")


class HypervisorType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    name: str
    add_script: str = ""
    destroy_script: str = ""
    # Valeurs par défaut des args pour créer un host de test (sauf l'identifiant).
    test_host_params: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _PROXMOX_NAME_RE.fullmatch(v):
            raise ValueError(f"name {v!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$")
        return v


class Hypervisor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    address: str
    ssh_user: str = "root"
    ssh_port: int = 22
    ssh_key_path: str
    pve_node: str = "pve"
    hypervisor_type: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _PROXMOX_NAME_RE.fullmatch(v):
            raise ValueError(f"name {v!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$")
        return v


class CaddyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_api: str = "http://caddy:2019"
    portal_host: str = "portal"


class CloudflareManagerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = ""
    api_key: str = ""


class LogsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    loki_push_url: str | None = None
    loki_query_url: str | None = None
    grafana_url: str | None = None
    module: str = "devpod"
    push_token: str | None = None  # littéral ou ${vault://...}/${env://...}
    # Client OAuth Keycloak du login SSO de Grafana lui-même — distinct de
    # push_token qui authentifie les collecteurs Alloy vers Loki. Auth/token/
    # userinfo URL dérivées de auth.oidc.issuer (même realm Keycloak).
    grafana_oauth_client_id: str = "agflow-grafana"
    grafana_oauth_client_secret: str | None = None


class EventsProducerConfig(BaseModel):
    """Producteur d'events vers le module workflow (contrat producteur d'events).

    Le portail émet déjà des events applicatifs en interne (bus `portal.events`) ;
    ce bloc active leur relais signé HMAC vers le module workflow. `source_id` est
    l'UUID attribué par le workflow à l'enregistrement de la source ; `secret_slug`
    référence le secret HMAC partagé, stocké comme secret système (jamais inline ici).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    # URL de base du module workflow (endpoint d'ingestion : `{url}/events/{source_id}`).
    workflow_base_url: str = ""
    # UUID de la source, attribué côté workflow à l'enregistrement.
    source_id: str = ""
    # Slug du secret système portant la clé HMAC partagée.
    secret_slug: str = "workflow_events_hmac"
    # Valeur du champ système `_source` (identifie l'application émettrice).
    source_uri: str = "urn:yoops:devpod"
    # Liste blanche des types d'events relayés (vide = aucun relais, même si enabled).
    # L'intersection avec le registre réel est refaite à l'abonnement (défensif).
    events: list[str] = Field(default_factory=list)


class GlobalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    server: ServerConfig
    auth: AuthConfig
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    devpod: DevpodConfig = Field(default_factory=DevpodConfig)
    hosts: list[HostConfig] = Field(default_factory=list)
    hypervisor_types: list[HypervisorType] = Field(default_factory=list)
    hypervisors: list[Hypervisor] = Field(default_factory=list)
    caddy: CaddyConfig = Field(default_factory=CaddyConfig)
    cloudflare_manager: CloudflareManagerConfig = Field(default_factory=CloudflareManagerConfig)
    logs: LogsConfig = Field(default_factory=LogsConfig)
    events_producer: EventsProducerConfig = Field(default_factory=EventsProducerConfig)

    @model_validator(mode="before")
    @classmethod
    def _migrate_proxmox_nodes(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "proxmox_nodes" in data and "hypervisors" not in data:
            nodes = data.pop("proxmox_nodes")
            migrated = []
            for n in nodes or []:
                if isinstance(n, dict):
                    n = {k: v for k, v in n.items() if k != "script_url"}
                migrated.append(n)
            data["hypervisors"] = migrated
        return data


class ProfileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Scope
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")


_WORKSPACE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")


class UserDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ide: str = "openvscode"
    idle_timeout: str = "4h"


class HarpocrateUserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = ""


class GitCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    host: str
    kind: Literal["ssh", "token"]
    key_path: str = ""
    username: str = ""
    token: str = ""


class WorkspaceExpose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hostname: str = ""


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    branch: str = ""
    git_credential: str = ""


class WorkspaceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    branch: str = ""
    git_credential: str = ""
    host: str = ""
    template: str = ""
    devcontainer_path: str = ""
    recipes: list[str] = Field(default_factory=list)
    ide: str = ""
    idle_timeout: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    expose: WorkspaceExpose = Field(default_factory=WorkspaceExpose)
    extra_sources: list[SourceSpec] = Field(default_factory=list)
    ssh_key: bool = False
    profile: ProfileRef | None = None
    start_recipes: list[str] = Field(default_factory=list)
    default_start: str = ""
    recipe_volumes: list[str] = Field(default_factory=list)
    init_recipes: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    # Spec 35 : types d'agents à configurer dans le workspace (accès direct MCP).
    agents: list[str] = Field(default_factory=list)
    # Épingle « garder actif » (enabler 6016436b) : exempte le workspace de toute
    # suggestion d'arrêt pour inactivité, quel que soit son idle.
    keep_active: bool = False
    # Surcharge ponctuelle de la limite mémoire du conteneur (enabler 59864c37) :
    # "" = hériter de devpod.defaults.memory_limit.
    memory_limit: str = ""

    @field_validator("memory_limit")
    @classmethod
    def validate_memory_limit(cls, v: str) -> str:
        return _validate_memory_limit(v)

    @field_validator("agents")
    @classmethod
    def validate_agent_ids(cls, v: list[str]) -> list[str]:
        from portal.agents.models import AGENT_ID_RE

        for aid in v:
            if not AGENT_ID_RE.fullmatch(aid):
                raise ValueError(
                    f"agent id {aid!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$"
                )
        return v

    @field_validator("start_recipes", "init_recipes")
    @classmethod
    def validate_recipe_ids(cls, v: list[str]) -> list[str]:
        from portal.recipes.models import _RECIPE_ID_RE

        for rid in v:
            if not _RECIPE_ID_RE.fullmatch(rid):
                raise ValueError(
                    f"recipe id {rid!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$"
                )
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _WORKSPACE_NAME_RE.fullmatch(v):
            raise ValueError(f"name '{v}' must match ^[a-z0-9][a-z0-9-]{{0,30}}[a-z0-9]$")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v and v.startswith("-"):
            raise ValueError("source must not start with '-' (argument injection prevention)")
        return v


class UserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    secret_ns: str
    culture: str = "fr"
    defaults: UserDefaults = Field(default_factory=UserDefaults)
    harpocrate: HarpocrateUserConfig = Field(default_factory=HarpocrateUserConfig)
    git_credentials: list[GitCredential] = Field(default_factory=list)
    workspaces: list[WorkspaceSpec] = Field(default_factory=list)

    @field_validator("secret_ns")
    @classmethod
    def validate_secret_ns(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError as e:
            raise ValueError(f"secret_ns must be a valid UUID, got: {v!r}") from e
        return str(uuid.UUID(v))
