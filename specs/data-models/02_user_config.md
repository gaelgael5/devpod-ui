# 02 — Configuration utilisateur

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | `UserConfig` (workspaces, git_credentials, defaults, secret_ns) |
| Chemin | `/data/users/{login}/config.yaml` |
| Fonction | `config/store.py :: save_user()`, `provision_user()` |
| Format | YAML |
| Écriture | Atomique : tempfile + `os.replace()` |

Un fichier par utilisateur. Login validé par regex. Tous les chemins passent par `safe_user_path()`.

---

## Modèle Python (Pydantic v2)

```python
from __future__ import annotations
import re, uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from portal.profiles.models import Scope

class ProfileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope                          # 'shared' | 'user'
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")

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
    key_path: str = ""     # chemin filesystem vers clé privée (kind=ssh)
    username: str = ""
    token: str = ""        # token en clair (géré par le backend secrets)

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
    name: str                              # DNS-safe ^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$
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

class UserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    secret_ns: str             # UUID — namespace Harpocrate de l'utilisateur
    defaults: UserDefaults = Field(default_factory=UserDefaults)
    harpocrate: HarpocrateUserConfig = Field(default_factory=HarpocrateUserConfig)
    git_credentials: list[GitCredential] = Field(default_factory=list)
    workspaces: list[WorkspaceSpec] = Field(default_factory=list)
```

---

## Tables SQL équivalentes

```sql
CREATE TABLE users (
    login        TEXT PRIMARY KEY,      -- identifiant OIDC (preferred_username)
    version      TEXT NOT NULL,
    secret_ns    UUID NOT NULL UNIQUE,  -- namespace Harpocrate
    -- defaults
    default_ide           TEXT NOT NULL DEFAULT 'openvscode',
    default_idle_timeout  TEXT NOT NULL DEFAULT '4h',
    -- harpocrate user
    harpocrate_api_key    TEXT NOT NULL DEFAULT '',  -- chiffré
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE git_credentials (
    id         SERIAL PRIMARY KEY,
    login      TEXT NOT NULL REFERENCES users(login) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    host       TEXT NOT NULL,
    kind       TEXT NOT NULL,             -- 'ssh' | 'token'
    -- kind = 'ssh'
    key_path   TEXT NOT NULL DEFAULT '',  -- chemin filesystem vers id_ed25519 (0o600)
    public_key TEXT NOT NULL DEFAULT '',  -- contenu OpenSSH .pub (à déposer sur GitHub/GitLab)
    -- kind = 'token'
    username   TEXT NOT NULL DEFAULT '',
    token      TEXT NOT NULL DEFAULT '',  -- chiffré
    UNIQUE (login, name)
);

CREATE TABLE workspaces (
    id                  SERIAL PRIMARY KEY,
    login               TEXT NOT NULL REFERENCES users(login) ON DELETE CASCADE,
    name                TEXT NOT NULL,  -- DNS-safe
    source              TEXT NOT NULL,
    branch              TEXT NOT NULL DEFAULT '',
    git_credential      TEXT NOT NULL DEFAULT '',
    host                TEXT NOT NULL DEFAULT '',
    template            TEXT NOT NULL DEFAULT '',
    devcontainer_path   TEXT NOT NULL DEFAULT '',
    recipes             TEXT[] NOT NULL DEFAULT '{}',
    ide                 TEXT NOT NULL DEFAULT '',
    idle_timeout        TEXT NOT NULL DEFAULT '',
    env                 JSONB NOT NULL DEFAULT '{}',
    expose_hostname     TEXT NOT NULL DEFAULT '',
    ssh_key             BOOLEAN NOT NULL DEFAULT FALSE,
    profile_scope       TEXT,           -- 'shared' | 'user' | NULL
    profile_slug        TEXT,
    start_recipes       TEXT[] NOT NULL DEFAULT '{}',
    default_start       TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (login, name)
);

CREATE TABLE workspace_extra_sources (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    url             TEXT NOT NULL,
    branch          TEXT NOT NULL DEFAULT '',
    git_credential  TEXT NOT NULL DEFAULT ''
);
```
