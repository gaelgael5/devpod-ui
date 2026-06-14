from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    log: LogConfig = Field(default_factory=LogConfig)


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
    key_path: str = ""
    proxmox_node: str = ""  # nœud PVE qui a créé/gère cette VM


_PROXMOX_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")


class ProxmoxNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    address: str
    ssh_user: str = "root"
    ssh_port: int = 22
    ssh_key_path: str
    pve_node: str = "pve"
    script_url: str = ""
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
    proxmox_nodes: list[ProxmoxNode] = Field(default_factory=list)
    caddy: CaddyConfig = Field(default_factory=CaddyConfig)
    cloudflare_manager: CloudflareManagerConfig = Field(default_factory=CloudflareManagerConfig)


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
