# M1 — Fondations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Établir le squelette Python du portail avec les modèles pydantic v2 de configuration, le store fichier avec écriture atomique, et le résolveur de secrets avec ses deux backends (inline YAML et Harpocrate).

**Architecture:** Un package `portal` organisé en sous-modules (`config/`, `secrets/`). La configuration est chargée depuis des fichiers YAML et validée par des modèles pydantic v2 avec `extra="forbid"`. Les secrets sont résolus via un type `Secret` opaque dont la valeur n'est accessible que via `.reveal()`, garantissant qu'aucun secret n'est accidentellement loggé. Chaque écriture de config passe par `tempfile + os.replace` (atomique).

**Tech Stack:** Python 3.12, uv, pydantic v2, pydantic-settings, pyyaml, httpx, structlog, pytest, pytest-asyncio, ruff, mypy (strict)

---

## File Structure

```
backend/
├── pyproject.toml
├── src/
│   └── portal/
│       ├── __init__.py
│       ├── config/
│       │   ├── __init__.py
│       │   ├── models.py          # GlobalConfig, UserConfig + sous-modèles
│       │   └── store.py           # safe_user_path, ensure_user_dir, load_global,
│       │                          #   load_user, load_user_config, save_user
│       └── secrets/
│           ├── __init__.py
│           ├── types.py           # classe Secret (repr masqué)
│           ├── resolver.py        # Scope, SecretAccessError, resolve()
│           └── backends/
│               ├── __init__.py
│               ├── base.py        # protocole SecretsBackend
│               ├── inline.py      # InlineBackend (lecture YAML local)
│               └── harpocrate.py  # HarpocrateBackend (client httpx)
└── tests/
    ├── __init__.py
    ├── conftest.py                # fixtures: tmp_data_root, *_yaml, sample_user_config
    ├── config/
    │   ├── __init__.py
    │   ├── test_models.py
    │   └── test_store.py
    └── secrets/
        ├── __init__.py
        ├── test_types.py
        ├── test_resolver.py
        ├── test_inline.py
        ├── test_harpocrate.py
        └── test_integration.py
```

---

## Task 0: Branche de développement

**Files:** aucun

- [ ] **Step 0.1: Créer et basculer sur la branche `dev`**

```bash
git checkout -b dev
```

Expected: `Switched to a new branch 'dev'`

---

## Task 1: Squelette du projet

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/portal/__init__.py` (et sous-packages)
- Create: `backend/tests/__init__.py` (et sous-packages)

- [ ] **Step 1.1: Créer `backend/pyproject.toml`**

```toml
[project]
name = "workspace-portal"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "structlog>=24.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
    "mypy>=1.10",
    "types-pyyaml",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/portal"]

[tool.ruff]
line-length = 100
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["portal"]
mypy_path = "src"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 1.2: Créer les répertoires et fichiers `__init__.py`**

```bash
cd backend
mkdir -p src/portal/config
mkdir -p src/portal/secrets/backends
mkdir -p tests/config
mkdir -p tests/secrets
touch src/portal/__init__.py
touch src/portal/config/__init__.py
touch src/portal/secrets/__init__.py
touch src/portal/secrets/backends/__init__.py
touch tests/__init__.py
touch tests/config/__init__.py
touch tests/secrets/__init__.py
```

- [ ] **Step 1.3: Installer les dépendances**

```bash
cd backend && uv sync --extra dev
```

Expected: `Resolved N packages` sans erreur

- [ ] **Step 1.4: Vérifier ruff + mypy tournent sans erreur**

```bash
cd backend && uv run ruff check src/ && uv run mypy src/
```

Expected: aucune erreur (fichiers vides)

- [ ] **Step 1.5: Commit**

```bash
git add backend/
git commit -m "chore: initialise le squelette du backend (pyproject.toml + arbo portal)"
```

---

## Task 2: Modèles de configuration (`config/models.py`)

**Files:**
- Create: `backend/src/portal/config/models.py`
- Create: `backend/tests/config/test_models.py`

- [ ] **Step 2.1: Écrire les tests**

Créer `backend/tests/config/test_models.py` :

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from portal.config.models import GlobalConfig, UserConfig

VALID_GLOBAL = {
    "version": "1",
    "server": {
        "listen": "0.0.0.0:8080",
        "base_domain": "dev.yoops.org",
        "external_url": "https://dev.yoops.org",
        "dev_mode": False,
        "log": {"level": "info", "format": "text", "output": ""},
    },
    "auth": {
        "oidc": {
            "issuer": "https://security.yoops.org/realms/yoops",
            "client_id": "workspace-portal",
            "client_secret": "${env://OIDC_CLIENT_SECRET}",
            "scopes": ["openid", "profile", "email", "roles"],
            "role_claim": "realm_access.roles",
            "admin_role": "admin",
            "user_role": "dev",
            "username_claim": "preferred_username",
        }
    },
    "secrets": {
        "backend": "harpocrate",
        "harpocrate": {
            "url": "https://harpocrate.yoops.org",
            "api_key": "${env://HARPOCRATE_API_KEY}",
            "base_path": "devpod",
        },
    },
    "devpod": {
        "binary": "/usr/local/bin/devpod",
        "defaults": {"ide": "openvscode", "idle_timeout": "2h", "dotfiles": ""},
        "client_cert_path": "/data/certs/portal",
    },
    "hosts": [
        {
            "name": "local",
            "default": True,
            "type": "docker-tls",
            "docker_host": "tcp://192.168.1.50:2376",
        }
    ],
    "caddy": {"admin_api": "http://caddy:2019"},
    "cloudflare_manager": {
        "url": "http://cloudflare-manager:8000",
        "api_key": "${env://CFM_API_KEY}",
    },
}

VALID_USER = {
    "version": "1",
    "secret_ns": "a3f8c1d2-4b56-7890-abcd-ef1234567890",
    "defaults": {"ide": "openvscode", "idle_timeout": "4h"},
    "harpocrate": {"api_key": ""},
    "git_credentials": [
        {
            "name": "github-perso",
            "host": "github.com",
            "kind": "ssh",
            "key_path": "keys/git/github_ed25519",
        }
    ],
    "workspaces": [
        {
            "name": "agflow",
            "source": "git@github.com:gaelgael5/ag.flow.git",
            "branch": "main",
            "git_credential": "github-perso",
            "host": "local",
            "template": "python-uv",
            "devcontainer_path": "",
            "recipes": ["claude-code", "aider"],
            "ide": "openvscode",
            "idle_timeout": "4h",
            "env": {"ANTHROPIC_API_KEY": "${vault://llm/anthropic_key}"},
            "expose": {"hostname": ""},
        }
    ],
}


# ─── GlobalConfig ──────────────────────────────────────────────────────────

def test_global_config_parses_valid():
    cfg = GlobalConfig.model_validate(VALID_GLOBAL)
    assert cfg.version == "1"
    assert cfg.server.base_domain == "dev.yoops.org"
    assert cfg.auth.oidc.client_id == "workspace-portal"
    assert cfg.secrets.backend == "harpocrate"
    assert len(cfg.hosts) == 1
    assert cfg.hosts[0].name == "local"


def test_global_config_rejects_unknown_field():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GlobalConfig.model_validate({**VALID_GLOBAL, "surprise": True})


# ─── UserConfig ───────────────────────────────────────────────────────────

def test_user_config_parses_valid():
    cfg = UserConfig.model_validate(VALID_USER)
    assert cfg.secret_ns == "a3f8c1d2-4b56-7890-abcd-ef1234567890"
    assert len(cfg.workspaces) == 1
    assert cfg.workspaces[0].name == "agflow"


def test_user_config_rejects_unknown_field():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UserConfig.model_validate({**VALID_USER, "mystery": True})


def test_user_config_rejects_invalid_secret_ns():
    with pytest.raises(ValidationError, match="secret_ns"):
        UserConfig.model_validate({**VALID_USER, "secret_ns": "not-a-uuid"})


# ─── WorkspaceSpec.name ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name",
    [
        "Ab",       # majuscule
        "a..b",     # point non autorisé
        "../x",     # traversal
        "a_b",      # underscore non autorisé
        "a" * 40,   # trop long (> 32 chars)
        "a",        # trop court (1 char, min = 2)
        "-abc",     # commence par tiret
        "abc-",     # finit par tiret
    ],
)
def test_workspace_name_rejects_invalid(name: str):
    ws = {**VALID_USER["workspaces"][0], "name": name}
    with pytest.raises(ValidationError, match="name"):
        UserConfig.model_validate({**VALID_USER, "workspaces": [ws]})


@pytest.mark.parametrize(
    "name",
    [
        "agflow",
        "my-workspace",
        "ab",        # 2 chars : minimum valide
        "a" * 32,    # 32 chars : maximum valide (1 + 30 + 1)
    ],
)
def test_workspace_name_accepts_valid(name: str):
    ws = {**VALID_USER["workspaces"][0], "name": name}
    cfg = UserConfig.model_validate({**VALID_USER, "workspaces": [ws]})
    assert cfg.workspaces[0].name == name
```

- [ ] **Step 2.2: Lancer les tests — vérifier l'échec**

```bash
cd backend && uv run pytest tests/config/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'portal.config.models'`

- [ ] **Step 2.3: Implémenter `backend/src/portal/config/models.py`**

```python
from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class LogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["debug", "info", "warn", "error"] = "info"
    format: Literal["text", "json"] = "text"
    output: str = ""


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listen: str = "0.0.0.0:8080"
    base_domain: str
    external_url: str
    dev_mode: bool = False
    log: LogConfig = LogConfig()


class OidcConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer: str
    client_id: str
    client_secret: str
    scopes: list[str] = ["openid", "profile", "email", "roles"]
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
    harpocrate: HarpocrateGlobalConfig = HarpocrateGlobalConfig()


class DevpodDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ide: str = "openvscode"
    idle_timeout: str = "2h"
    dotfiles: str = ""


class DevpodConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binary: str = "/usr/local/bin/devpod"
    defaults: DevpodDefaults = DevpodDefaults()
    client_cert_path: str = "/data/certs/portal"


class HostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    default: bool = False
    type: Literal["docker-tls", "ssh"]
    docker_host: str = ""
    address: str = ""
    key_path: str = ""


class CaddyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_api: str = "http://caddy:2019"


class CloudflareManagerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = ""
    api_key: str = ""


class GlobalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    server: ServerConfig
    auth: AuthConfig
    secrets: SecretsConfig = SecretsConfig()
    devpod: DevpodConfig = DevpodConfig()
    hosts: list[HostConfig] = []
    caddy: CaddyConfig = CaddyConfig()
    cloudflare_manager: CloudflareManagerConfig = CloudflareManagerConfig()


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


class WorkspaceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    branch: str = "main"
    git_credential: str = ""
    host: str = ""
    template: str = ""
    devcontainer_path: str = ""
    recipes: list[str] = []
    ide: str = ""
    idle_timeout: str = ""
    env: dict[str, str] = {}
    expose: WorkspaceExpose = WorkspaceExpose()

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _WORKSPACE_NAME_RE.fullmatch(v):
            raise ValueError(
                f"name '{v}' must match ^[a-z0-9][a-z0-9-]{{0,30}}[a-z0-9]$"
            )
        return v


class UserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    secret_ns: str
    defaults: UserDefaults = UserDefaults()
    harpocrate: HarpocrateUserConfig = HarpocrateUserConfig()
    git_credentials: list[GitCredential] = []
    workspaces: list[WorkspaceSpec] = []

    @field_validator("secret_ns")
    @classmethod
    def validate_secret_ns(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError as e:
            raise ValueError(f"secret_ns must be a valid UUID, got: {v!r}") from e
        return v
```

- [ ] **Step 2.4: Lancer les tests — vérifier la réussite**

```bash
cd backend && uv run pytest tests/config/test_models.py -v
```

Expected: tous les tests PASS

- [ ] **Step 2.5: Vérifier ruff + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```

Expected: aucune erreur

- [ ] **Step 2.6: Commit**

```bash
git add backend/
git commit -m "feat(config): modèles pydantic v2 GlobalConfig et UserConfig"
```

---

## Task 3: Store fichier atomique (`config/store.py`)

**Files:**
- Create: `backend/src/portal/config/store.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/config/test_store.py`

- [ ] **Step 3.1: Créer `backend/tests/conftest.py`**

```python
from __future__ import annotations

import uuid

import pytest
import yaml

from portal.config.models import UserConfig


@pytest.fixture
def tmp_data_root(tmp_path, monkeypatch):
    """Redirige PORTAL_DATA_ROOT vers un répertoire temporaire."""
    monkeypatch.setenv("PORTAL_DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def global_config_yaml() -> str:
    return """\
version: "1"
server:
  listen: "0.0.0.0:8080"
  base_domain: "dev.yoops.org"
  external_url: "https://dev.yoops.org"
  dev_mode: false
  log:
    level: "info"
    format: "text"
    output: ""
auth:
  oidc:
    issuer: "https://security.yoops.org/realms/yoops"
    client_id: "workspace-portal"
    client_secret: "${env://OIDC_CLIENT_SECRET}"
    scopes: ["openid", "profile", "email", "roles"]
    role_claim: "realm_access.roles"
    admin_role: "admin"
    user_role: "dev"
    username_claim: "preferred_username"
secrets:
  backend: "inline"
devpod:
  binary: "/usr/local/bin/devpod"
  defaults:
    ide: "openvscode"
    idle_timeout: "2h"
    dotfiles: ""
  client_cert_path: "/data/certs/portal"
hosts:
  - name: "local"
    default: true
    type: "docker-tls"
    docker_host: "tcp://192.168.1.50:2376"
caddy:
  admin_api: "http://caddy:2019"
cloudflare_manager:
  url: ""
  api_key: ""
"""


@pytest.fixture
def user_config_yaml() -> str:
    return """\
version: "1"
secret_ns: "a3f8c1d2-4b56-7890-abcd-ef1234567890"
defaults:
  ide: "openvscode"
  idle_timeout: "4h"
harpocrate:
  api_key: ""
git_credentials: []
workspaces: []
"""


@pytest.fixture
def sample_user_config() -> UserConfig:
    return UserConfig.model_validate({
        "version": "1",
        "secret_ns": str(uuid.uuid4()),
        "defaults": {"ide": "openvscode", "idle_timeout": "4h"},
        "harpocrate": {"api_key": ""},
        "git_credentials": [],
        "workspaces": [],
    })
```

- [ ] **Step 3.2: Écrire les tests du store**

Créer `backend/tests/config/test_store.py` :

```python
from __future__ import annotations

import os

import pytest
import yaml

from portal.config.models import GlobalConfig, UserConfig
from portal.config.store import (
    ensure_user_dir,
    load_global,
    load_user,
    load_user_config,
    safe_user_path,
    save_user,
)


# ─── safe_user_path ───────────────────────────────────────────────────────────

def test_safe_user_path_returns_correct_path(tmp_data_root):
    p = safe_user_path("alice", "config.yaml")
    assert p == tmp_data_root / "users" / "alice" / "config.yaml"


def test_safe_user_path_no_parts_returns_user_dir(tmp_data_root):
    p = safe_user_path("alice")
    assert p == tmp_data_root / "users" / "alice"


def test_safe_user_path_rejects_dotdot(tmp_data_root):
    with pytest.raises(ValueError, match="Invalid path component"):
        safe_user_path("alice", "..", "etc", "passwd")


def test_safe_user_path_rejects_slash_in_part(tmp_data_root):
    with pytest.raises(ValueError, match="Invalid path component"):
        safe_user_path("alice", "keys/git")


def test_safe_user_path_rejects_invalid_login(tmp_data_root):
    with pytest.raises(ValueError, match="Invalid login"):
        safe_user_path("../evil", "config.yaml")


def test_safe_user_path_rejects_login_with_slash(tmp_data_root):
    with pytest.raises(ValueError, match="Invalid login"):
        safe_user_path("alice/bob", "config.yaml")


# ─── ensure_user_dir ──────────────────────────────────────────────────────────

def test_ensure_user_dir_creates_all_subdirs(tmp_data_root):
    ensure_user_dir("alice")
    expected = [
        tmp_data_root / "users" / "alice",
        tmp_data_root / "users" / "alice" / "keys" / "git",
        tmp_data_root / "users" / "alice" / "keys" / "workspaces",
        tmp_data_root / "users" / "alice" / "recipes",
        tmp_data_root / "users" / "alice" / "templates",
        tmp_data_root / "users" / "alice" / "devpod",
    ]
    for d in expected:
        assert d.is_dir(), f"Missing: {d}"


def test_ensure_user_dir_is_idempotent(tmp_data_root):
    ensure_user_dir("alice")
    ensure_user_dir("alice")  # pas d'erreur


# ─── load_global ──────────────────────────────────────────────────────────────

def test_load_global_parses_yaml(tmp_data_root, global_config_yaml):
    (tmp_data_root / "config.yaml").write_text(global_config_yaml)
    cfg = load_global()
    assert cfg.server.base_domain == "dev.yoops.org"
    assert cfg.hosts[0].name == "local"


def test_load_global_raises_on_missing_file(tmp_data_root):
    with pytest.raises(FileNotFoundError):
        load_global()


# ─── load_user ────────────────────────────────────────────────────────────────

def test_load_user_parses_yaml(tmp_data_root, user_config_yaml):
    ensure_user_dir("alice")
    (tmp_data_root / "users" / "alice" / "config.yaml").write_text(user_config_yaml)
    cfg = load_user("alice")
    assert cfg.version == "1"
    assert cfg.secret_ns == "a3f8c1d2-4b56-7890-abcd-ef1234567890"


def test_load_user_raises_on_missing_file(tmp_data_root):
    ensure_user_dir("alice")
    with pytest.raises(FileNotFoundError):
        load_user("alice")


# ─── save_user (écriture atomique) ────────────────────────────────────────────

def test_save_user_writes_file(tmp_data_root, sample_user_config):
    ensure_user_dir("alice")
    save_user("alice", sample_user_config)
    p = tmp_data_root / "users" / "alice" / "config.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text())
    assert data["version"] == "1"


def test_save_user_atomic_crash_leaves_original_intact(tmp_data_root, sample_user_config, monkeypatch):
    """Un crash avant os.replace (simulé) ne corrompt pas la config existante."""
    ensure_user_dir("alice")
    config_path = tmp_data_root / "users" / "alice" / "config.yaml"
    original = "version: '1'\nsecret_ns: 'aaaaaaaa-0000-0000-0000-000000000000'\n"
    config_path.write_text(original)

    def exploding_replace(src: str, dst: str) -> None:
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(os, "replace", exploding_replace)

    with pytest.raises(OSError, match="simulated crash"):
        save_user("alice", sample_user_config)

    assert config_path.read_text() == original


# ─── load_user_config (validation croisée) ────────────────────────────────────

def test_load_user_config_passes_when_host_exists(tmp_data_root, global_config_yaml):
    (tmp_data_root / "config.yaml").write_text(global_config_yaml)
    ensure_user_dir("alice")
    user_yaml = """\
version: "1"
secret_ns: "a3f8c1d2-4b56-7890-abcd-ef1234567890"
git_credentials: []
workspaces:
  - name: myws
    source: "git@github.com:foo/bar.git"
    host: "local"
"""
    (tmp_data_root / "users" / "alice" / "config.yaml").write_text(user_yaml)
    global_cfg = load_global()
    cfg = load_user_config("alice", global_cfg)
    assert cfg.workspaces[0].host == "local"


def test_load_user_config_rejects_unknown_host(tmp_data_root, global_config_yaml):
    (tmp_data_root / "config.yaml").write_text(global_config_yaml)
    ensure_user_dir("alice")
    user_yaml = """\
version: "1"
secret_ns: "a3f8c1d2-4b56-7890-abcd-ef1234567890"
git_credentials: []
workspaces:
  - name: myws
    source: "git@github.com:foo/bar.git"
    host: "nonexistent-host"
"""
    (tmp_data_root / "users" / "alice" / "config.yaml").write_text(user_yaml)
    global_cfg = load_global()
    with pytest.raises(ValueError, match="nonexistent-host"):
        load_user_config("alice", global_cfg)


def test_load_user_config_rejects_unknown_git_credential(tmp_data_root, global_config_yaml):
    (tmp_data_root / "config.yaml").write_text(global_config_yaml)
    ensure_user_dir("alice")
    user_yaml = """\
version: "1"
secret_ns: "a3f8c1d2-4b56-7890-abcd-ef1234567890"
git_credentials: []
workspaces:
  - name: myws
    source: "git@github.com:foo/bar.git"
    git_credential: "ghost-cred"
"""
    (tmp_data_root / "users" / "alice" / "config.yaml").write_text(user_yaml)
    global_cfg = load_global()
    with pytest.raises(ValueError, match="ghost-cred"):
        load_user_config("alice", global_cfg)
```

- [ ] **Step 3.3: Lancer les tests — vérifier l'échec**

```bash
cd backend && uv run pytest tests/config/test_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'portal.config.store'`

- [ ] **Step 3.4: Implémenter `backend/src/portal/config/store.py`**

```python
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import yaml

from .models import GlobalConfig, UserConfig

_LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,61}[a-z0-9]$")


def _data_root() -> Path:
    return Path(os.environ.get("PORTAL_DATA_ROOT", "/data"))


def safe_user_path(login: str, *parts: str) -> Path:
    if not _LOGIN_RE.fullmatch(login):
        raise ValueError(f"Invalid login: {login!r}")
    base = _data_root() / "users" / login
    result = base
    for part in parts:
        if "/" in part or "\\" in part or ".." in part:
            raise ValueError(f"Invalid path component: {part!r}")
        result = result / part
    resolved = result.resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError(f"Path escapes user directory: {result}")
    return result


def ensure_user_dir(login: str) -> None:
    user_dir = safe_user_path(login)
    subdirs = [
        ("keys", "git"),
        ("keys", "workspaces"),
        ("recipes",),
        ("templates",),
        ("devpod",),
    ]
    user_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(user_dir, 0o700)
    for sub in subdirs:
        safe_user_path(login, *sub).mkdir(parents=True, exist_ok=True)


def load_global() -> GlobalConfig:
    path = _data_root() / "config.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    return GlobalConfig.model_validate(data)


def load_user(login: str) -> UserConfig:
    path = safe_user_path(login, "config.yaml")
    with open(path) as f:
        data = yaml.safe_load(f)
    return UserConfig.model_validate(data)


def load_user_config(login: str, global_cfg: GlobalConfig) -> UserConfig:
    cfg = load_user(login)
    known_hosts = {h.name for h in global_cfg.hosts}
    known_creds = {c.name for c in cfg.git_credentials}
    for ws in cfg.workspaces:
        if ws.host and ws.host not in known_hosts:
            raise ValueError(
                f"Workspace '{ws.name}' references unknown host: {ws.host!r}"
            )
        if ws.git_credential and ws.git_credential not in known_creds:
            raise ValueError(
                f"Workspace '{ws.name}' references unknown git_credential:"
                f" {ws.git_credential!r}"
            )
    return cfg


def save_user(login: str, cfg: UserConfig) -> None:
    path = safe_user_path(login, "config.yaml")
    parent = path.parent
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(cfg.model_dump(mode="json"), f, default_flow_style=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

- [ ] **Step 3.5: Lancer les tests — vérifier la réussite**

```bash
cd backend && uv run pytest tests/config/ -v
```

Expected: tous les tests PASS

- [ ] **Step 3.6: Vérifier ruff + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```

Expected: aucune erreur

- [ ] **Step 3.7: Commit**

```bash
git add backend/
git commit -m "feat(config): store atomique, safe_user_path, ensure_user_dir, load_user_config"
```

---

## Task 4: Type `Secret` (`secrets/types.py`)

**Files:**
- Create: `backend/src/portal/secrets/types.py`
- Create: `backend/tests/secrets/test_types.py`

- [ ] **Step 4.1: Écrire les tests**

Créer `backend/tests/secrets/test_types.py` :

```python
from __future__ import annotations

import structlog.testing

from portal.secrets.types import Secret


def test_reveal_returns_value():
    assert Secret("hunter2").reveal() == "hunter2"


def test_repr_masks_value():
    assert repr(Secret("hunter2")) == "Secret(***)"
    assert "hunter2" not in repr(Secret("hunter2"))


def test_str_masks_value():
    assert str(Secret("hunter2")) == "***"
    assert "hunter2" not in str(Secret("hunter2"))


def test_f_string_does_not_leak():
    s = Secret("hunter2")
    assert "hunter2" not in f"secret={s}"


def test_format_does_not_leak():
    s = Secret("hunter2")
    assert "hunter2" not in "secret={}".format(s)


def test_equality():
    assert Secret("abc") == Secret("abc")
    assert Secret("abc") != Secret("xyz")


def test_does_not_leak_in_structlog():
    s = Secret("verysecretvalue")
    with structlog.testing.capture_logs() as cap:
        structlog.get_logger().info("processing", secret=s)
    for event in cap:
        for v in event.values():
            assert "verysecretvalue" not in str(v)
```

- [ ] **Step 4.2: Lancer les tests — vérifier l'échec**

```bash
cd backend && uv run pytest tests/secrets/test_types.py -v
```

Expected: `ModuleNotFoundError: No module named 'portal.secrets.types'`

- [ ] **Step 4.3: Implémenter `backend/src/portal/secrets/types.py`**

```python
from __future__ import annotations


class Secret:
    """Wrapper opaque pour une valeur secrète.

    La valeur réelle n'est accessible que via .reveal(). __repr__ et __str__
    retournent "***" pour prévenir toute fuite accidentelle dans les logs.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    def __str__(self) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)
```

- [ ] **Step 4.4: Lancer les tests — vérifier la réussite**

```bash
cd backend && uv run pytest tests/secrets/test_types.py -v
```

Expected: tous les tests PASS

- [ ] **Step 4.5: Commit**

```bash
git add backend/
git commit -m "feat(secrets): type Secret avec repr masqué et non-fuite"
```

---

## Task 5: Résolveur de secrets (`secrets/resolver.py`)

**Files:**
- Create: `backend/src/portal/secrets/backends/base.py`
- Create: `backend/src/portal/secrets/resolver.py`
- Create: `backend/tests/secrets/test_resolver.py`

- [ ] **Step 5.1: Écrire les tests**

Créer `backend/tests/secrets/test_resolver.py` :

```python
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from portal.secrets.backends.base import SecretsBackend
from portal.secrets.resolver import Scope, SecretAccessError, resolve
from portal.secrets.types import Secret

USER_NS = "a3f8c1d2-4b56-7890-abcd-ef1234567890"
OTHER_NS = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_SCOPE = Scope(kind="user", secret_ns=USER_NS, login="alice")
GLOBAL_SCOPE = Scope(kind="global", secret_ns="", login="")


def _backend(return_value: str = "resolved") -> SecretsBackend:
    b = MagicMock(spec=SecretsBackend)
    b.get.return_value = return_value
    b.base_path = "devpod"
    return b


# ─── Littéraux ────────────────────────────────────────────────────────────────

def test_literal_returned_unchanged():
    result = resolve("hello world", USER_SCOPE, _backend())
    assert result == "hello world"
    assert not isinstance(result, Secret)


def test_empty_string_returned_unchanged():
    result = resolve("", USER_SCOPE, _backend())
    assert result == ""


# ─── ${env://VAR} ─────────────────────────────────────────────────────────────

def test_env_ref_returns_secret(monkeypatch):
    monkeypatch.setenv("MY_TEST_TOKEN", "env_value")
    result = resolve("${env://MY_TEST_TOKEN}", USER_SCOPE, _backend())
    assert isinstance(result, Secret)
    assert result.reveal() == "env_value"


def test_env_ref_raises_on_missing_var(monkeypatch):
    monkeypatch.delenv("ABSENT_VAR", raising=False)
    with pytest.raises(SecretAccessError, match="ABSENT_VAR"):
        resolve("${env://ABSENT_VAR}", USER_SCOPE, _backend())


# ─── ${vault://PATH} scope user ───────────────────────────────────────────────

def test_vault_user_prefixes_namespace():
    b = _backend("secret_value")
    result = resolve("${vault://git/my_key}", USER_SCOPE, b)
    b.get.assert_called_once_with(f"devpod/{USER_NS}/git/my_key")
    assert isinstance(result, Secret)
    assert result.reveal() == "secret_value"


def test_vault_user_rejects_absolute_path():
    with pytest.raises(SecretAccessError, match="absolute"):
        resolve("${vault:///etc/passwd}", USER_SCOPE, _backend())


def test_vault_user_rejects_dotdot():
    with pytest.raises(SecretAccessError, match=r"\.\.|traversal"):
        resolve("${vault://../other/secret}", USER_SCOPE, _backend())


def test_vault_user_rejects_foreign_namespace():
    with pytest.raises(SecretAccessError, match="namespace"):
        resolve(f"${{vault://{OTHER_NS}/secret}}", USER_SCOPE, _backend())


# ─── ${vault://PATH} scope global ─────────────────────────────────────────────

def test_vault_global_uses_path_as_is():
    b = _backend("global_secret")
    result = resolve("${vault://devpod/somekey}", GLOBAL_SCOPE, b)
    b.get.assert_called_once_with("devpod/somekey")
    assert isinstance(result, Secret)
```

- [ ] **Step 5.2: Lancer les tests — vérifier l'échec**

```bash
cd backend && uv run pytest tests/secrets/test_resolver.py -v
```

Expected: erreurs d'import

- [ ] **Step 5.3: Implémenter `backend/src/portal/secrets/backends/base.py`**

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretsBackend(Protocol):
    base_path: str

    def get(self, full_path: str) -> str:
        ...
```

- [ ] **Step 5.4: Implémenter `backend/src/portal/secrets/resolver.py`**

```python
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from .backends.base import SecretsBackend
from .types import Secret

_SECRET_REF_RE = re.compile(r"^\$\{(vault|env)://(.+)\}$")


class SecretAccessError(Exception):
    pass


@dataclass
class Scope:
    kind: Literal["user", "global"]
    secret_ns: str = ""
    login: str = ""


def resolve(value: str, scope: Scope, backend: SecretsBackend) -> str | Secret:
    m = _SECRET_REF_RE.fullmatch(value)
    if not m:
        return value

    kind, path = m.group(1), m.group(2)

    if kind == "env":
        env_val = os.environ.get(path)
        if env_val is None:
            raise SecretAccessError(f"Environment variable not found: {path!r}")
        return Secret(env_val)

    # vault://
    if scope.kind == "user":
        _validate_user_vault_path(path, scope.secret_ns)
        full_path = f"{backend.base_path}/{scope.secret_ns}/{path}"
    else:
        full_path = path

    return Secret(backend.get(full_path))


def _validate_user_vault_path(path: str, secret_ns: str) -> None:
    if path.startswith("/"):
        raise SecretAccessError(
            f"User vault path must not be absolute (starts with '/'): {path!r}"
        )
    parts = path.split("/")
    if ".." in parts:
        raise SecretAccessError(
            f"User vault path must not contain '..' traversal: {path!r}"
        )
    for part in parts:
        try:
            parsed_uuid = uuid.UUID(part)
            if str(parsed_uuid) != secret_ns:
                raise SecretAccessError(
                    f"User vault path contains foreign namespace UUID: {part!r}"
                )
        except ValueError:
            pass  # pas un UUID — segment normal
```

- [ ] **Step 5.5: Lancer les tests — vérifier la réussite**

```bash
cd backend && uv run pytest tests/secrets/test_resolver.py -v
```

Expected: tous les tests PASS

- [ ] **Step 5.6: Vérifier ruff + mypy**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```

Expected: aucune erreur

- [ ] **Step 5.7: Commit**

```bash
git add backend/
git commit -m "feat(secrets): résolveur (Scope, SecretAccessError, resolve, validation paths)"
```

---

## Task 6: Backend inline (`secrets/backends/inline.py`)

**Files:**
- Create: `backend/src/portal/secrets/backends/inline.py`
- Create: `backend/tests/secrets/test_inline.py`

- [ ] **Step 6.1: Écrire les tests**

Créer `backend/tests/secrets/test_inline.py` :

```python
from __future__ import annotations

import pytest
import yaml

from portal.secrets.backends.inline import InlineBackend

USER_NS = "a3f8c1d2-4b56-7890-abcd-ef1234567890"
BASE = "devpod"


def test_get_returns_string_value(tmp_path):
    (tmp_path / "secrets.yaml").write_text(yaml.dump({"git": {"my_token": "abc123"}}))
    backend = InlineBackend(user_secrets_path=tmp_path / "secrets.yaml", base_path=BASE)
    assert backend.get(f"{BASE}/{USER_NS}/git/my_token") == "abc123"


def test_get_raises_key_error_on_missing_key(tmp_path):
    (tmp_path / "secrets.yaml").write_text(yaml.dump({"git": {}}))
    backend = InlineBackend(user_secrets_path=tmp_path / "secrets.yaml", base_path=BASE)
    with pytest.raises(KeyError):
        backend.get(f"{BASE}/{USER_NS}/git/missing")


def test_get_raises_on_missing_file(tmp_path):
    backend = InlineBackend(
        user_secrets_path=tmp_path / "nonexistent.yaml", base_path=BASE
    )
    with pytest.raises(FileNotFoundError):
        backend.get(f"{BASE}/{USER_NS}/git/key")


def test_get_nested_key(tmp_path):
    (tmp_path / "secrets.yaml").write_text(
        yaml.dump({"llm": {"anthropic": {"key": "sk-abc"}}})
    )
    backend = InlineBackend(user_secrets_path=tmp_path / "secrets.yaml", base_path=BASE)
    assert backend.get(f"{BASE}/{USER_NS}/llm/anthropic/key") == "sk-abc"
```

- [ ] **Step 6.2: Lancer les tests — vérifier l'échec**

```bash
cd backend && uv run pytest tests/secrets/test_inline.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 6.3: Implémenter `backend/src/portal/secrets/backends/inline.py`**

```python
from __future__ import annotations

import uuid
from pathlib import Path

import yaml


class InlineBackend:
    """Lit les secrets depuis un fichier YAML local (user ou global)."""

    base_path: str

    def __init__(self, user_secrets_path: Path, base_path: str = "devpod") -> None:
        self._path = user_secrets_path
        self.base_path = base_path

    def get(self, full_path: str) -> str:
        with open(self._path) as f:
            data: dict[str, object] = yaml.safe_load(f) or {}

        # Retirer le préfixe "base_path/"
        prefix = self.base_path + "/"
        rel = full_path[len(prefix):] if full_path.startswith(prefix) else full_path

        # Retirer le segment UUID (namespace) s'il est en tête
        parts = rel.split("/")
        try:
            uuid.UUID(parts[0])
            parts = parts[1:]
        except (ValueError, IndexError):
            pass

        node: object = data
        for part in parts:
            if not isinstance(node, dict):
                raise KeyError(f"Path not traversable at {part!r} in {full_path!r}")
            if part not in node:
                raise KeyError(f"Key {part!r} not found in {full_path!r}")
            node = node[part]

        if not isinstance(node, str):
            raise KeyError(f"Value at {full_path!r} is not a string: {type(node)}")
        return node
```

- [ ] **Step 6.4: Lancer les tests — vérifier la réussite**

```bash
cd backend && uv run pytest tests/secrets/test_inline.py -v
```

Expected: tous les tests PASS

- [ ] **Step 6.5: Commit**

```bash
git add backend/
git commit -m "feat(secrets): backend inline (lecture YAML local)"
```

---

## Task 7: Backend Harpocrate (`secrets/backends/harpocrate.py`)

**Files:**
- Create: `backend/src/portal/secrets/backends/harpocrate.py`
- Create: `backend/tests/secrets/test_harpocrate.py`

- [ ] **Step 7.1: Écrire les tests**

Créer `backend/tests/secrets/test_harpocrate.py` :

```python
from __future__ import annotations

import httpx
import pytest

from portal.secrets.backends.harpocrate import HarpocrateBackend


def _backend(handler) -> HarpocrateBackend:
    return HarpocrateBackend(
        url="https://harpocrate.example.com",
        api_key="test-key",
        base_path="devpod",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_get_returns_value():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": "my_secret"})

    assert _backend(handler).get("devpod/ns/git/token") == "my_secret"


def test_get_raises_key_error_on_404():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with pytest.raises(KeyError, match="not found"):
        _backend(handler).get("devpod/ns/git/missing")


def test_get_sends_api_key_header():
    received: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        received.update(dict(req.headers))
        return httpx.Response(200, json={"value": "v"})

    HarpocrateBackend(
        url="https://harpocrate.example.com",
        api_key="my-secret-key",
        base_path="devpod",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).get("devpod/ns/key")

    assert received.get("x-api-key") == "my-secret-key"


def test_get_raises_on_http_error():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    with pytest.raises(httpx.HTTPStatusError):
        _backend(handler).get("devpod/ns/key")
```

- [ ] **Step 7.2: Lancer les tests — vérifier l'échec**

```bash
cd backend && uv run pytest tests/secrets/test_harpocrate.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 7.3: Implémenter `backend/src/portal/secrets/backends/harpocrate.py`**

```python
from __future__ import annotations

import httpx


class HarpocrateBackend:
    """Client HTTP synchrone vers Harpocrate. API key transmise en header X-Api-Key."""

    base_path: str

    def __init__(
        self,
        url: str,
        api_key: str,
        base_path: str = "devpod",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._api_key = api_key
        self.base_path = base_path
        self._client = http_client or httpx.Client()

    def get(self, full_path: str) -> str:
        response = self._client.get(
            f"{self._url}/secrets/{full_path}",
            headers={"X-Api-Key": self._api_key},
        )
        if response.status_code == 404:
            raise KeyError(f"Secret not found at {full_path!r}: {response.text}")
        response.raise_for_status()
        return str(response.json()["value"])
```

- [ ] **Step 7.4: Lancer les tests — vérifier la réussite**

```bash
cd backend && uv run pytest tests/secrets/test_harpocrate.py -v
```

Expected: tous les tests PASS

- [ ] **Step 7.5: Commit**

```bash
git add backend/
git commit -m "feat(secrets): backend Harpocrate (client httpx, header X-Api-Key)"
```

---

## Task 8: Tests d'intégration secrets

**Files:**
- Create: `backend/tests/secrets/test_integration.py`

- [ ] **Step 8.1: Écrire les tests d'intégration**

Créer `backend/tests/secrets/test_integration.py` :

```python
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import yaml

from portal.secrets.backends.inline import InlineBackend
from portal.secrets.resolver import Scope, SecretAccessError, resolve
from portal.secrets.types import Secret

USER_NS = "a3f8c1d2-4b56-7890-abcd-ef1234567890"
USER_SCOPE = Scope(kind="user", secret_ns=USER_NS, login="alice")


def test_inline_backend_works_as_fallback(tmp_path):
    """Vérifie que le backend inline fonctionne en remplacement de Harpocrate."""
    (tmp_path / "secrets.yaml").write_text(yaml.dump({"llm": {"key": "inline_value"}}))
    inline = InlineBackend(user_secrets_path=tmp_path / "secrets.yaml", base_path="devpod")
    result = resolve("${vault://llm/key}", USER_SCOPE, inline)
    assert isinstance(result, Secret)
    assert result.reveal() == "inline_value"


def test_secret_repr_safe_in_exception_message():
    s = Secret("top_secret_value")
    try:
        raise ValueError(f"processing failed for secret={s}")
    except ValueError as e:
        assert "top_secret_value" not in str(e)


def test_literal_is_plain_string_not_secret():
    b = MagicMock()
    b.base_path = "devpod"
    result = resolve("plain value", USER_SCOPE, b)
    assert isinstance(result, str)
    assert not isinstance(result, Secret)
    b.get.assert_not_called()


def test_env_resolution_does_not_call_backend(monkeypatch):
    monkeypatch.setenv("PORTAL_TEST_KEY", "from_env")
    b = MagicMock()
    b.base_path = "devpod"
    result = resolve("${env://PORTAL_TEST_KEY}", USER_SCOPE, b)
    assert isinstance(result, Secret)
    assert result.reveal() == "from_env"
    b.get.assert_not_called()
```

- [ ] **Step 8.2: Lancer tous les tests**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: tous les tests PASS

- [ ] **Step 8.3: Vérifier ruff + mypy complet**

```bash
cd backend && uv run ruff check src/ tests/ && uv run mypy src/
```

Expected: aucune erreur

- [ ] **Step 8.4: Commit final M1**

```bash
git add backend/
git commit -m "test(secrets): tests d'intégration — fallback inline + non-fuite Secret"
```

---

## Vérification finale (Definition of Done M1)

- [ ] `uv run pytest tests/ -v` → 0 failed
- [ ] `uv run ruff check src/ tests/` → 0 erreurs
- [ ] `uv run mypy src/` → 0 erreurs
- [ ] `safe_user_path` couvre 100% des constructions de chemin user
- [ ] Aucun `print()`, aucun secret en clair dans le code
- [ ] Écriture atomique testée avec crash simulé
- [ ] Rejets sécurité path traversal, secret_ns étranger, env var manquante : tous testés
- [ ] Pièges §C-18, §D-22/23, §G-34 cochés dans `03_PITFALLS.md`
