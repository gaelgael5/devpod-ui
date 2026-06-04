from __future__ import annotations

from pathlib import Path

import pytest


def test_build_env_sets_devpod_home_for_user(tmp_data_root: Path, global_cfg) -> None:
    from portal.config.models import WorkspaceSpec
    from portal.devpod.env import build_env

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git", host="local")
    env = build_env(login="alice", ws_spec=ws, global_cfg=global_cfg)

    expected_home = str(tmp_data_root / "users" / "alice" / "devpod")
    assert env["DEVPOD_HOME"] == expected_home


def test_build_env_sets_docker_vars_for_docker_tls_host(tmp_data_root: Path, global_cfg) -> None:
    from portal.config.models import WorkspaceSpec
    from portal.devpod.env import build_env

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git", host="local")
    env = build_env(login="alice", ws_spec=ws, global_cfg=global_cfg)

    assert env["DOCKER_HOST"] == "tcp://192.168.1.50:2376"
    assert env["DOCKER_TLS_VERIFY"] == "1"
    assert "DOCKER_CERT_PATH" in env


def test_build_env_no_docker_vars_for_ssh_host(tmp_data_root: Path, global_cfg) -> None:
    from portal.config.models import WorkspaceSpec
    from portal.devpod.env import build_env

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git", host="node-ssh")
    env = build_env(login="alice", ws_spec=ws, global_cfg=global_cfg)

    assert "DOCKER_HOST" not in env
    assert "DOCKER_TLS_VERIFY" not in env


def test_build_env_uses_default_host_when_none_specified(tmp_data_root: Path, global_cfg) -> None:
    from portal.config.models import WorkspaceSpec
    from portal.devpod.env import build_env

    # host="" (chaîne vide = valeur par défaut) → doit utiliser l'host "local" (default=True)
    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git")
    env = build_env(login="alice", ws_spec=ws, global_cfg=global_cfg)

    assert env["DOCKER_HOST"] == "tcp://192.168.1.50:2376"


def test_build_env_raises_for_unknown_host(tmp_data_root: Path, global_cfg) -> None:
    from portal.config.models import WorkspaceSpec
    from portal.devpod.env import UnknownHostError, build_env

    ws = WorkspaceSpec(name="myapp", source="git@github.com:user/repo.git", host="nonexistent")
    with pytest.raises(UnknownHostError):
        build_env(login="alice", ws_spec=ws, global_cfg=global_cfg)
