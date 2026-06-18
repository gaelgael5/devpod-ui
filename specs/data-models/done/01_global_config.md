# 01 — Configuration globale

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | `GlobalConfig` |
| Chemin | `/data/config.yaml` |
| Fonction | `config/store.py :: save_global()` |
| Format | YAML |
| Écriture | Atomique : tempfile + `os.replace()` |

Singleton. Contient tous les paramètres d'infrastructure : serveur, OIDC, secrets, devpod, hosts Docker/SSH, hyperviseurs Proxmox, Caddy, Cloudflare.

---

## Modèle Python (Pydantic v2)

```python
from __future__ import annotations
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
    workspace_host: str = ""
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
    proxmox_node: str = ""
    vmid: str = ""

class HypervisorType(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = ""
    name: str                   # DNS-safe ^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$
    add_script: str = ""
    destroy_script: str = ""

class Hypervisor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str                   # DNS-safe
    address: str
    ssh_user: str = "root"
    ssh_port: int = 22
    ssh_key_path: str
    pve_node: str = "pve"
    hypervisor_type: str = ""
    password: str = ""

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
```

---

## Tables SQL équivalentes

```sql
-- Singleton — toujours une seule ligne (id = 1)
-- Couvre : ServerConfig, LogConfig, AuthConfig/OidcConfig,
--          SecretsConfig/HarpocrateGlobalConfig, DevpodConfig/DevpodDefaults,
--          CaddyConfig, CloudflareManagerConfig
CREATE TABLE global_config (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version         TEXT NOT NULL,

    -- ServerConfig
    listen          TEXT NOT NULL DEFAULT '0.0.0.0:8080',
    base_domain     TEXT NOT NULL,
    external_url    TEXT NOT NULL,
    dev_mode        BOOLEAN NOT NULL DEFAULT FALSE,
    workspace_host  TEXT NOT NULL DEFAULT '',

    -- ServerConfig.log (LogConfig)
    log_level       TEXT NOT NULL DEFAULT 'info',   -- 'debug'|'info'|'warning'|'error'
    log_format      TEXT NOT NULL DEFAULT 'text',   -- 'text'|'json'
    log_output      TEXT NOT NULL DEFAULT '',

    -- AuthConfig.oidc (OidcConfig)
    oidc_issuer         TEXT NOT NULL,
    oidc_client_id      TEXT NOT NULL,
    oidc_client_secret  TEXT NOT NULL,              -- chiffré en base
    oidc_scopes         TEXT[] NOT NULL DEFAULT ARRAY['openid','profile','email','roles'],
    oidc_role_claim     TEXT NOT NULL DEFAULT 'realm_access.roles',
    oidc_admin_role     TEXT NOT NULL DEFAULT 'admin',
    oidc_user_role      TEXT NOT NULL DEFAULT 'dev',
    oidc_username_claim TEXT NOT NULL DEFAULT 'preferred_username',

    -- SecretsConfig
    secrets_backend  TEXT NOT NULL DEFAULT 'inline',  -- 'harpocrate'|'inline'

    -- SecretsConfig.harpocrate (HarpocrateGlobalConfig)
    harpocrate_url       TEXT NOT NULL DEFAULT '',
    harpocrate_api_key   TEXT NOT NULL DEFAULT '',    -- chiffré
    harpocrate_base_path TEXT NOT NULL DEFAULT 'devpod',

    -- DevpodConfig
    devpod_binary           TEXT NOT NULL DEFAULT '/usr/local/bin/devpod',
    devpod_client_cert_path TEXT NOT NULL DEFAULT '/data/certs/portal',

    -- DevpodConfig.defaults (DevpodDefaults)
    devpod_ide          TEXT NOT NULL DEFAULT 'openvscode',
    devpod_idle_timeout TEXT NOT NULL DEFAULT '2h',
    devpod_dotfiles     TEXT NOT NULL DEFAULT '',

    -- CaddyConfig
    caddy_admin_api   TEXT NOT NULL DEFAULT 'http://caddy:2019',
    caddy_portal_host TEXT NOT NULL DEFAULT 'portal',

    -- CloudflareManagerConfig
    cf_url     TEXT NOT NULL DEFAULT '',
    cf_api_key TEXT NOT NULL DEFAULT '',              -- chiffré

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HostConfig — liste de hosts Docker/SSH
-- Lié implicitement à global_config (singleton) : pas de FK, une seule config globale.
CREATE TABLE hosts (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    is_default   BOOLEAN NOT NULL DEFAULT FALSE,
    type         TEXT NOT NULL,          -- 'docker-tls' | 'ssh'
    -- type=docker-tls
    docker_host  TEXT NOT NULL DEFAULT '',
    -- type=ssh
    address      TEXT NOT NULL DEFAULT '',
    key_path     TEXT NOT NULL DEFAULT '',  -- chemin clé privée SSH sur le filesystem
    public_key   TEXT NOT NULL DEFAULT '',  -- clé publique SSH (OpenSSH format)
    -- Lien vers l'hyperviseur Proxmox qui a créé cette VM
    proxmox_node TEXT NOT NULL DEFAULT '' REFERENCES hypervisors(name)
                     ON DELETE SET DEFAULT DEFERRABLE INITIALLY DEFERRED,
    vmid         TEXT NOT NULL DEFAULT '',  -- VMID Proxmox de la VM associée
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HypervisorType — types d'hyperviseurs Proxmox (scripts add/destroy)
CREATE TABLE hypervisor_types (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,   -- DNS-safe
    label          TEXT NOT NULL DEFAULT '',
    add_script     TEXT NOT NULL DEFAULT '',
    destroy_script TEXT NOT NULL DEFAULT '',
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Hypervisor — nœuds Proxmox pilotables
CREATE TABLE hypervisors (
    id               SERIAL PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,   -- DNS-safe
    address          TEXT NOT NULL,
    ssh_user         TEXT NOT NULL DEFAULT 'root',
    ssh_port         INTEGER NOT NULL DEFAULT 22,
    ssh_key_path     TEXT NOT NULL,          -- chemin clé privée SSH
    pve_node         TEXT NOT NULL DEFAULT 'pve',
    hypervisor_type  TEXT NOT NULL DEFAULT ''
                         REFERENCES hypervisor_types(name)
                         ON DELETE SET DEFAULT,
    password         TEXT NOT NULL DEFAULT '',  -- chiffré
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
