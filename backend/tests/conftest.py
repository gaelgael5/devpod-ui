from __future__ import annotations

import uuid

import pytest

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
