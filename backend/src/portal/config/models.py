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
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email", "roles"])
    role_claim: str = "realm_access.roles"
    admin_role: str = "admin"
    user_role: str = "dev"
    username_claim: str = "preferred_username"


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


class DevpodDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ide: str = "openvscode"
    idle_timeout: str = "2h"
    dotfiles: str = ""


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
    # Préférences de stockage des secrets
    storage_type: Literal["local", "harpocrate"] = "local"
    vault_identifier: str = ""
    # Destination du host : workspaces (sélectionnable à la création) ou tests.
    usage: Literal["workspaces", "tests"] = "workspaces"


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
    password: str = ""

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
