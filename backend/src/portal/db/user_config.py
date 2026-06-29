"""Persistance UserConfig (users, git_credentials, workspaces, workspace_extra_sources)."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import (
    GitCredential,
    HarpocrateUserConfig,
    ProfileRef,
    SourceSpec,
    UserConfig,
    UserDefaults,
    WorkspaceExpose,
    WorkspaceSpec,
)
from .tables import git_credentials, users, workspace_extra_sources, workspaces

_log = structlog.get_logger(__name__)


async def ensure_user_db(login: str, conn: AsyncConnection) -> None:
    """Garantit l'existence de la row users — idempotent.

    Appelé comme garde-FK avant toute opération qui dépend de users.login
    (pin setup, workspaces…). Couvre le cas où la session cookie survit à un
    restart/wipe DB sans que l'utilisateur soit repassé par le login.
    """
    existing = (
        await conn.execute(select(users.c.login).where(users.c.login == login))
    ).scalar_one_or_none()
    if existing is not None:
        return

    # Lire le secret_ns depuis le YAML (cohérence filesystem ↔ DB)
    from ..config.store import _data_root  # import lazy pour éviter les cycles

    config_path: Path = _data_root() / "users" / login / "config.yaml"
    try:
        with config_path.open(encoding="utf-8") as f:
            raw: dict[str, object] = yaml.safe_load(f) or {}
        secret_ns_str = str(raw.get("secret_ns", uuid.uuid4()))
    except OSError:
        secret_ns_str = str(uuid.uuid4())

    await conn.execute(
        insert(users).values(login=login, version="1", secret_ns=secret_ns_str)
    )
    _log.info("user_db_row_lazy_created", login=login)


async def load_user_db(login: str, conn: AsyncConnection) -> UserConfig:
    user_row = (
        await conn.execute(select(users).where(users.c.login == login))
    ).mappings().one_or_none()
    if user_row is None:
        raise FileNotFoundError(f"User {login!r} not found in DB")

    cred_rows = (
        await conn.execute(
            select(git_credentials)
            .where(git_credentials.c.login == login)
            .order_by(git_credentials.c.id)
        )
    ).mappings().all()

    ws_rows = (
        await conn.execute(
            select(workspaces)
            .where(workspaces.c.login == login)
            .order_by(workspaces.c.id)
        )
    ).mappings().all()

    ws_ids = [r["id"] for r in ws_rows]
    if ws_ids:
        _extra_result = await conn.execute(
            select(workspace_extra_sources)
            .where(workspace_extra_sources.c.workspace_id.in_(ws_ids))
            .order_by(
                workspace_extra_sources.c.workspace_id,
                workspace_extra_sources.c.position,
            )
        )
        extra_rows: list[Any] = [dict(r) for r in _extra_result.mappings().all()]
    else:
        extra_rows = []

    extras_by_ws: dict[int, list[Any]] = {}
    for e in extra_rows:
        extras_by_ws.setdefault(e["workspace_id"], []).append(e)

    return _build_user_config(dict(user_row), list(cred_rows), list(ws_rows), extras_by_ws)


async def save_user_db(login: str, cfg: UserConfig, conn: AsyncConnection) -> None:
    # Upsert user row
    existing = (
        await conn.execute(select(users.c.login).where(users.c.login == login))
    ).scalar_one_or_none()

    user_vals = {
        "login": login,
        "version": cfg.version,
        "secret_ns": str(cfg.secret_ns),
        "default_ide": cfg.defaults.ide,
        "default_idle_timeout": cfg.defaults.idle_timeout,
        "harpocrate_api_key": cfg.harpocrate.api_key,
    }
    if existing is None:
        await conn.execute(insert(users).values(**user_vals))
    else:
        await conn.execute(
            update(users).where(users.c.login == login).values(
                **{k: v for k, v in user_vals.items() if k != "login"},
                updated_at=func.now(),
            )
        )

    # Replace git credentials
    await conn.execute(delete(git_credentials).where(git_credentials.c.login == login))
    if cfg.git_credentials:
        await conn.execute(
            insert(git_credentials),
            [
                {
                    "login": login,
                    "name": c.name,
                    "host": c.host,
                    "kind": c.kind,
                    "key_path": c.key_path,
                    "public_key": "",
                    "username": c.username,
                    "token": c.token,
                }
                for c in cfg.git_credentials
            ],
        )

    # Replace workspaces (cascade removes extra_sources)
    await conn.execute(delete(workspaces).where(workspaces.c.login == login))
    if cfg.workspaces:
        result = await conn.execute(
            insert(workspaces).returning(workspaces.c.id, workspaces.c.name),
            [_ws_to_row(login, ws) for ws in cfg.workspaces],
        )
        ws_ids_by_name = {row["name"]: row["id"] for row in result.mappings().all()}

        extra_vals: list[dict[str, Any]] = []
        for ws in cfg.workspaces:
            ws_id = ws_ids_by_name[ws.name]
            for pos, src in enumerate(ws.extra_sources):
                extra_vals.append(
                    {
                        "workspace_id": ws_id,
                        "position": pos,
                        "url": src.url,
                        "branch": src.branch,
                        "git_credential": src.git_credential,
                    }
                )
        if extra_vals:
            await conn.execute(insert(workspace_extra_sources), extra_vals)


# ─── Private helpers ─────────────────────────────────────────────────────────


def _build_user_config(
    user_row: dict[str, Any],
    cred_rows: list[Any],
    ws_rows: list[Any],
    extras_by_ws: dict[int, list[Any]],
) -> UserConfig:
    return UserConfig(
        version=user_row["version"],
        secret_ns=str(user_row["secret_ns"]),
        defaults=UserDefaults(
            ide=user_row["default_ide"],
            idle_timeout=user_row["default_idle_timeout"],
        ),
        harpocrate=HarpocrateUserConfig(api_key=user_row["harpocrate_api_key"]),
        git_credentials=[_cred_row_to_model(dict(r)) for r in cred_rows],
        workspaces=[_ws_row_to_model(dict(r), extras_by_ws.get(r["id"], [])) for r in ws_rows],
    )


def _cred_row_to_model(row: dict[str, Any]) -> GitCredential:
    return GitCredential(
        name=row["name"],
        host=row["host"],
        kind=row["kind"],
        key_path=row["key_path"],
        username=row["username"],
        token=row["token"],
    )


def _ws_row_to_model(row: dict[str, Any], extra_rows: list[Any]) -> WorkspaceSpec:
    profile: ProfileRef | None = None
    if row["profile_scope"] and row["profile_slug"]:
        profile = ProfileRef(scope=row["profile_scope"], slug=row["profile_slug"])
    return WorkspaceSpec(
        name=row["name"],
        source=row["source"],
        branch=row["branch"],
        git_credential=row["git_credential"],
        host=row["host"],
        template=row["template"],
        devcontainer_path=row["devcontainer_path"],
        recipes=list(row["recipes"] or []),
        ide=row["ide"],
        idle_timeout=row["idle_timeout"],
        env=dict(row["env"] or {}),
        expose=WorkspaceExpose(hostname=row["expose_hostname"]),
        ssh_key=row["ssh_key"],
        profile=profile,
        start_recipes=list(row["start_recipes"] or []),
        default_start=row["default_start"],
        recipe_volumes=list(row["recipe_volumes"] or []),
        init_recipes=list(row["init_recipes"] or []),
        groups=list(row["groups"] or []),
        extra_sources=[
            SourceSpec(
                url=e["url"],
                branch=e["branch"],
                git_credential=e["git_credential"],
            )
            for e in extra_rows
        ],
    )


def _ws_to_row(login: str, ws: WorkspaceSpec) -> dict[str, Any]:
    return {
        "login": login,
        "name": ws.name,
        "source": ws.source,
        "branch": ws.branch,
        "git_credential": ws.git_credential,
        "host": ws.host,
        "template": ws.template,
        "devcontainer_path": ws.devcontainer_path,
        "recipes": list(ws.recipes),
        "ide": ws.ide,
        "idle_timeout": ws.idle_timeout,
        "env": dict(ws.env),
        "expose_hostname": ws.expose.hostname,
        "ssh_key": ws.ssh_key,
        "profile_scope": ws.profile.scope if ws.profile else None,
        "profile_slug": ws.profile.slug if ws.profile else None,
        "start_recipes": list(ws.start_recipes),
        "default_start": ws.default_start,
        "recipe_volumes": list(ws.recipe_volumes),
        "init_recipes": list(ws.init_recipes),
        "groups": list(ws.groups),
    }
