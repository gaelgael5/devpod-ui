from __future__ import annotations

import os

import pytest
import yaml

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


def test_save_user_atomic_crash_leaves_original_intact(
    tmp_data_root, sample_user_config, monkeypatch
):
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
