"""Persistance UserConfig (users, git_credentials, workspaces, workspace_extra_sources)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
from .tables import (
    git_credentials,
    user_termix_instance,
    users,
    workspace_extra_sources,
    workspaces,
)

_log = structlog.get_logger(__name__)


class UserNotProvisionedError(Exception):
    """Ligne users absente et ancre config.yaml illisible — re-login requis.

    Ne JAMAIS fabriquer un secret_ns de secours (bug 011) : le namespace
    Harpocrate est externe — un GUID inventé rendrait les secrets existants
    inaccessibles et divergerait du YAML recréé au prochain login.
    """

    def __init__(self, login: str) -> None:
        super().__init__(
            f"User {login!r} has no users row and no readable config.yaml — re-login required"
        )
        self.login = login


async def owner_identity_subject(login: str) -> dict[str, str]:
    """`{login, sub, email, identity}` du propriétaire — pour enrichir les events.

    Ouvre sa propre connexion (émission d'event best-effort, hors txn). Champs
    absents rendus "" (jamais None → pas de placeholder littéral côté template).
    """
    from .engine import _get_engine

    async with _get_engine().connect() as conn:
        row = (
            await conn.execute(
                select(users.c.sub, users.c.email, users.c.identity).where(users.c.login == login)
            )
        ).first()
    sub, email, identity = row if row is not None else (None, None, None)
    return {
        "login": login,
        "sub": sub or "",
        "email": email or "",
        "identity": identity or "",
    }


async def list_admin_logins(conn: AsyncConnection) -> list[str]:
    """Logins des utilisateurs admin (`users.is_admin`, persisté au login OIDC).

    Sert à pousser des connexions Termix aux admins (hosts d'infra, ressources) hors
    contexte de requête — le rôle OIDC n'étant pas disponible ailleurs (migration 101)."""
    rows = (
        (await conn.execute(select(users.c.login).where(users.c.is_admin.is_(True))))
        .scalars()
        .all()
    )
    return list(rows)


async def is_admin_db(login: str, conn: AsyncConnection) -> bool:
    """True si l'utilisateur est admin (`users.is_admin`, posé au login OIDC)."""
    return bool(
        (
            await conn.execute(select(users.c.is_admin).where(users.c.login == login))
        ).scalar_one_or_none()
    )


async def get_user_actor(login: str, conn: AsyncConnection) -> str | None:
    """Identité propagée aux services MCP (on-behalf-of) : `users.identity` (GUID).

    GUID-only : on ne retombe PAS sur le `sub`. None si l'identité n'est pas définie —
    l'appelant OBO n'émet alors aucune identité (fail-safe : l'objet reste attribué à la
    clé). L'utilisateur doit donc renseigner son identité dans son profil pour être
    propagé (bouton « Générer » ou saisie libre)."""
    row = (await conn.execute(select(users.c.identity).where(users.c.login == login))).first()
    if row is None:
        return None
    identity: str | None = row[0]
    return identity


async def ensure_user_db(login: str, conn: AsyncConnection) -> None:
    """Garantit l'existence de la row users — idempotent.

    Appelé comme garde-FK avant toute opération qui dépend de users.login
    (pin setup, workspaces…). Couvre le cas où la session cookie survit à un
    restart/wipe DB sans que l'utilisateur soit repassé par le login.

    Atomicité (bug 010) : l'INSERT porte un ON CONFLICT DO NOTHING — deux
    provisions concurrentes du même login n'échouent jamais en UniqueViolation
    et n'écrasent jamais une ligne existante. Le SELECT préalable n'est qu'un
    fast path (évite la lecture YAML), pas une garde de correction.
    """
    existing = (
        await conn.execute(select(users.c.login).where(users.c.login == login))
    ).scalar_one_or_none()
    if existing is not None:
        return

    # Lire le secret_ns depuis le YAML, seule ancre durable (cohérence
    # filesystem ↔ DB). S'il est illisible, échouer explicitement (bug 011).
    from ..config.store import safe_user_path  # import lazy pour éviter les cycles

    config_path: Path = safe_user_path(login, "config.yaml")
    try:
        with config_path.open(encoding="utf-8") as f:
            raw: dict[str, object] = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        _log.warning("user_not_provisioned", login=login, reason=str(exc))
        raise UserNotProvisionedError(login) from exc
    secret_ns_raw = raw.get("secret_ns")
    if not secret_ns_raw:
        _log.warning("user_not_provisioned", login=login, reason="secret_ns missing in config.yaml")
        raise UserNotProvisionedError(login)
    secret_ns_str = str(secret_ns_raw)

    result = await conn.execute(
        pg_insert(users)
        .values(login=login, version="1", secret_ns=secret_ns_str)
        .on_conflict_do_nothing(index_elements=[users.c.login])
    )
    if (result.rowcount or 0) > 0:
        _log.info("user_db_row_lazy_created", login=login)


async def user_exists_db(login: str, conn: AsyncConnection) -> bool:
    """True si la row users existe (garde de validation, spec 18 T3)."""
    return (
        await conn.execute(select(users.c.login).where(users.c.login == login))
    ).scalar_one_or_none() is not None


async def get_workspace_profile_ref_db(
    login: str, name: str, conn: AsyncConnection
) -> tuple[str, str] | None:
    """(scope, slug) du profil d'un workspace, ou None si sans profil (spec 18 T5)."""
    row = (
        (
            await conn.execute(
                select(workspaces.c.profile_scope, workspaces.c.profile_slug).where(
                    workspaces.c.login == login, workspaces.c.name == name
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or not row["profile_scope"] or not row["profile_slug"]:
        return None
    return (row["profile_scope"], row["profile_slug"])


async def list_users_db(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Tous les users pour la page Utilisateurs admin (spec 18 T4b).

    Agrège les instances Termix rattachées (N-N) dans `termix_instance_ids`.
    """
    uti = user_termix_instance
    rows = (
        (
            await conn.execute(
                select(
                    users.c.login,
                    users.c.email,
                    users.c.display_name,
                    func.array_remove(func.array_agg(uti.c.instance_id), None).label(
                        "termix_instance_ids"
                    ),
                )
                .select_from(users.outerjoin(uti, users.c.login == uti.c.login))
                .group_by(users.c.login, users.c.email, users.c.display_name)
                .order_by(users.c.login)
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def list_workspace_refs(login: str | None, conn: AsyncConnection) -> list[dict[str, Any]]:
    """Référentiel léger des workspaces déclarés : `login`, `name`, `host` (nœud).

    Source de vérité des workspaces *existants*, indépendante de workspace_status
    (un workspace déclaré mais sans ligne de statut « running » existe quand même).
    `login=None` → tous les users (vue admin) ; sinon restreint au login donné.
    """
    stmt = select(
        workspaces.c.login, workspaces.c.name, workspaces.c.host, workspaces.c.keep_active
    )
    if login is not None:
        stmt = stmt.where(workspaces.c.login == login)
    rows = (
        (await conn.execute(stmt.order_by(workspaces.c.login, workspaces.c.name))).mappings().all()
    )
    return [dict(r) for r in rows]


async def load_user_db(login: str, conn: AsyncConnection) -> UserConfig:
    user_row = (
        (await conn.execute(select(users).where(users.c.login == login))).mappings().one_or_none()
    )
    if user_row is None:
        raise FileNotFoundError(f"User {login!r} not found in DB")

    cred_rows = (
        (
            await conn.execute(
                select(git_credentials)
                .where(git_credentials.c.login == login)
                .order_by(git_credentials.c.id)
            )
        )
        .mappings()
        .all()
    )

    ws_rows = (
        (
            await conn.execute(
                select(workspaces).where(workspaces.c.login == login).order_by(workspaces.c.id)
            )
        )
        .mappings()
        .all()
    )

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
    # Upsert atomique de la ligne users (bug 010) : INSERT … ON CONFLICT remplace
    # le check-then-insert qui levait UniqueViolation sous concurrence.
    user_vals: dict[str, Any] = {
        "login": login,
        "version": cfg.version,
        "secret_ns": str(cfg.secret_ns),
        "default_ide": cfg.defaults.ide,
        "default_idle_timeout": cfg.defaults.idle_timeout,
        "harpocrate_api_key": cfg.harpocrate.api_key,
        "culture": cfg.culture,
    }
    set_vals: dict[str, Any] = {k: v for k, v in user_vals.items() if k != "login"}
    set_vals["updated_at"] = func.now()
    await conn.execute(
        pg_insert(users)
        .values(**user_vals)
        .on_conflict_do_update(index_elements=[users.c.login], set_=set_vals)
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
        culture=user_row["culture"],
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
        agents=list(row["agents"] or []),
        keep_active=row["keep_active"],
        memory_limit=row["memory_limit"],
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
        "agents": list(ws.agents),
        "keep_active": ws.keep_active,
        "memory_limit": ws.memory_limit,
    }
