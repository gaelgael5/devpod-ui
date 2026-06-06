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


def test_user_config_normalizes_secret_ns_to_lowercase():
    data = {**VALID_USER, "secret_ns": "A3F8C1D2-4B56-7890-ABCD-EF1234567890"}
    cfg = UserConfig.model_validate(data)
    assert cfg.secret_ns == "a3f8c1d2-4b56-7890-abcd-ef1234567890"


# ─── WorkspaceSpec.name ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "Ab",  # majuscule
        "a..b",  # point non autorisé
        "../x",  # traversal
        "a_b",  # underscore non autorisé
        "a" * 40,  # trop long (> 32 chars)
        "a",  # trop court (1 char, min = 2)
        "-abc",  # commence par tiret
        "abc-",  # finit par tiret
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
        "ab",  # 2 chars : minimum valide
        "a" * 32,  # 32 chars : maximum valide (1 + 30 + 1)
    ],
)
def test_workspace_name_accepts_valid(name: str):
    ws = {**VALID_USER["workspaces"][0], "name": name}
    cfg = UserConfig.model_validate({**VALID_USER, "workspaces": [ws]})
    assert cfg.workspaces[0].name == name
