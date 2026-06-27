from __future__ import annotations

import os
import re
from pathlib import Path

from .models import GlobalConfig, UserConfig

_LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,38}[a-z0-9]$")


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
    """Retourne la GlobalConfig depuis le cache DB.

    Si aucune config n'a encore été sauvegardée (premier démarrage),
    retourne une config bootstrap vide pour permettre le CRUD admin
    (hyperviseurs, types…) avant la configuration initiale.
    """
    from portal.db.global_config import get_cached_global
    from .models import AuthConfig, OidcConfig, ServerConfig

    try:
        return get_cached_global()
    except RuntimeError:
        return GlobalConfig(
            version="1",
            server=ServerConfig(base_domain="", external_url=""),
            auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        )


async def load_user(login: str) -> UserConfig:
    from portal.db.engine import _get_engine
    from portal.db.user_config import load_user_db

    async with _get_engine().connect() as conn:
        return await load_user_db(login, conn)


async def load_user_config(login: str, global_cfg: GlobalConfig) -> UserConfig:
    cfg = await load_user(login)
    known_hosts = {h.name for h in global_cfg.hosts}
    known_creds = {c.name for c in cfg.git_credentials}
    for ws in cfg.workspaces:
        if ws.host and ws.host not in known_hosts:
            raise ValueError(f"Workspace '{ws.name}' references unknown host: {ws.host!r}")
        if ws.git_credential and ws.git_credential not in known_creds:
            raise ValueError(
                f"Workspace '{ws.name}' references unknown git_credential: {ws.git_credential!r}"
            )
    return cfg


async def save_user(login: str, cfg: UserConfig) -> None:
    from portal.db.engine import _get_engine
    from portal.db.user_config import save_user_db

    async with _get_engine().begin() as conn:
        await save_user_db(login, cfg, conn)


async def save_global(cfg: GlobalConfig) -> None:
    from portal.db.engine import _get_engine
    from portal.db.global_config import save_global_db

    async with _get_engine().begin() as conn:
        await save_global_db(cfg, conn)
