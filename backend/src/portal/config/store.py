from __future__ import annotations

import contextlib
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
    if not result.is_relative_to(base):
        raise ValueError(f"Path escapes user directory: {result!r}")
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
        sub_dir = safe_user_path(login, *sub)
        sub_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(sub_dir, 0o700)


def load_global() -> GlobalConfig:
    path = _data_root() / "config.yaml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return GlobalConfig.model_validate(data)


def load_user(login: str) -> UserConfig:
    path = safe_user_path(login, "config.yaml")
    with open(path, encoding="utf-8") as f:
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
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(cfg.model_dump(mode="json"), f, default_flow_style=False)
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
