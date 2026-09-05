from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import (
    mcp_apikey,
    mcp_audit_log,
    mcp_backend,
    mcp_backend_key,
    mcp_workspace_profile,
)

# Rétention des clés API révoquées : supprimées ce délai après leur révocation.
REVOKED_APIKEY_RETENTION_HOURS = 24

# Fenêtre de grâce à la rotation d'une clé workspace : l'ancienne génération reste
# valide ce délai (l'agent en cours garde son token, pas de ré-auth), puis expire.
WORKSPACE_KEY_ROTATION_GRACE_S = 900

_BACKEND_COLS = [
    mcp_backend.c.id,
    mcp_backend.c.owner_login,
    mcp_backend.c.namespace,
    mcp_backend.c.name,
    mcp_backend.c.url,
    mcp_backend.c.transport,
    mcp_backend.c.auth_scheme,
    mcp_backend.c.forward_identity,
    mcp_backend.c.enabled,
    mcp_backend.c.app_url,
    mcp_backend.c.oauth_auth_url,
    mcp_backend.c.quarantine_disabled,
    mcp_backend.c.created_at,
    mcp_backend.c.updated_at,
]


async def insert_backend(
    conn: AsyncConnection,
    *,
    id: str,
    owner_login: str,
    namespace: str,
    name: str,
    url: str,
    transport: str,
    auth_scheme: str = "bearer",
    forward_identity: bool = False,
    app_url: str = "",
    oauth_auth_url: str = "",
    quarantine_disabled: bool = False,
) -> None:
    await conn.execute(
        insert(mcp_backend).values(
            id=id,
            owner_login=owner_login,
            namespace=namespace,
            name=name,
            url=url,
            transport=transport,
            auth_scheme=auth_scheme,
            forward_identity=forward_identity,
            app_url=app_url,
            oauth_auth_url=oauth_auth_url,
            quarantine_disabled=quarantine_disabled,
        )
    )


async def list_all_enabled_backends(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Tous les backends enabled (tous owners) — usage monitoring système."""
    rows = (
        (
            await conn.execute(
                select(
                    mcp_backend.c.id,
                    mcp_backend.c.owner_login,
                    mcp_backend.c.namespace,
                    mcp_backend.c.name,
                    mcp_backend.c.url,
                    mcp_backend.c.transport,
                    mcp_backend.c.auth_scheme,
                    mcp_backend.c.enabled,
                    mcp_backend.c.quarantine_disabled,
                ).where(mcp_backend.c.enabled.is_(True))
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def list_backends(conn: AsyncConnection, owner_login: str) -> list[dict[str, Any]]:
    q = (
        select(*_BACKEND_COLS)
        .where(mcp_backend.c.owner_login == owner_login)
        .order_by(mcp_backend.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def get_backend(
    conn: AsyncConnection, owner_login: str, backend_id: str
) -> dict[str, Any] | None:
    q = select(*_BACKEND_COLS).where(
        mcp_backend.c.id == backend_id,
        mcp_backend.c.owner_login == owner_login,
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def backend_exists(conn: AsyncConnection, backend_id: str) -> bool:
    """Vérifie qu'un backend existe (sans filtre owner — la sécurité est au niveau dispatch)."""
    q = select(mcp_backend.c.id).where(mcp_backend.c.id == backend_id)
    return (await conn.execute(q)).first() is not None


async def update_backend(
    conn: AsyncConnection,
    owner_login: str,
    backend_id: str,
    *,
    name: str,
    url: str,
    transport: str,
    enabled: bool,
    auth_scheme: str = "bearer",
    forward_identity: bool = False,
    app_url: str = "",
    oauth_auth_url: str = "",
    quarantine_disabled: bool = False,
) -> bool:
    q = (
        update(mcp_backend)
        .where(mcp_backend.c.id == backend_id, mcp_backend.c.owner_login == owner_login)
        .values(
            name=name,
            url=url,
            transport=transport,
            enabled=enabled,
            auth_scheme=auth_scheme,
            forward_identity=forward_identity,
            app_url=app_url,
            oauth_auth_url=oauth_auth_url,
            quarantine_disabled=quarantine_disabled,
            updated_at=func.now(),
        )
        .returning(mcp_backend.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def delete_backend(conn: AsyncConnection, owner_login: str, backend_id: str) -> bool:
    q = (
        delete(mcp_backend)
        .where(mcp_backend.c.id == backend_id, mcp_backend.c.owner_login == owner_login)
        .returning(mcp_backend.c.id)
    )
    return (await conn.execute(q)).first() is not None


# ---------------------------------------------------------------------------
# Backend keys
# ---------------------------------------------------------------------------

_KEY_COLS = [
    mcp_backend_key.c.id,
    mcp_backend_key.c.backend_id,
    mcp_backend_key.c.slug,
    mcp_backend_key.c.description,
    mcp_backend_key.c.storage_type,
    mcp_backend_key.c.secret_value_vault_ref,
    mcp_backend_key.c.vault_identifier,
    mcp_backend_key.c.enabled,
    mcp_backend_key.c.created_at,
]


async def insert_backend_key(
    conn: AsyncConnection,
    *,
    id: str,
    backend_id: str,
    slug: str,
    description: str,
    storage_type: str,
    secret_value_local: bytes | None,
    secret_value_vault_ref: str | None,
    vault_identifier: str | None,
) -> None:
    await conn.execute(
        insert(mcp_backend_key).values(
            id=id,
            backend_id=backend_id,
            slug=slug,
            description=description,
            storage_type=storage_type,
            secret_value_local=secret_value_local,
            secret_value_vault_ref=secret_value_vault_ref,
            vault_identifier=vault_identifier,
        )
    )


async def list_backend_keys(conn: AsyncConnection, backend_id: str) -> list[dict[str, Any]]:
    q = (
        select(*_KEY_COLS)
        .where(mcp_backend_key.c.backend_id == backend_id)
        .order_by(mcp_backend_key.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def get_backend_key(
    conn: AsyncConnection, backend_id: str, key_id: str
) -> dict[str, Any] | None:
    q = select(*_KEY_COLS).where(
        mcp_backend_key.c.id == key_id,
        mcp_backend_key.c.backend_id == backend_id,
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def get_backend_key_secret(
    conn: AsyncConnection, backend_id: str, key_id: str
) -> dict[str, Any] | None:
    """Récupère le secret chiffré d'une clé de service — usage RUNTIME uniquement.

    Contrairement à `get_backend_key`/`list_backend_keys`, sélectionne
    `secret_value_local` (blob chiffré KEK). Réservé à la résolution du secret
    sortant au runtime ; ne JAMAIS l'exposer dans un listing/registre.
    """
    row = (
        (
            await conn.execute(
                select(
                    mcp_backend_key.c.storage_type,
                    mcp_backend_key.c.secret_value_local,
                    mcp_backend_key.c.secret_value_vault_ref,
                ).where(
                    mcp_backend_key.c.id == key_id,
                    mcp_backend_key.c.backend_id == backend_id,
                )
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def delete_backend_key(conn: AsyncConnection, backend_id: str, key_id: str) -> bool:
    q = (
        delete(mcp_backend_key)
        .where(mcp_backend_key.c.id == key_id, mcp_backend_key.c.backend_id == backend_id)
        .returning(mcp_backend_key.c.id)
    )
    return (await conn.execute(q)).first() is not None


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

_APIKEY_COLS = [
    mcp_apikey.c.id,
    mcp_apikey.c.owner_login,
    mcp_apikey.c.label,
    mcp_apikey.c.kind,
    mcp_apikey.c.revoked,
    mcp_apikey.c.created_at,
    mcp_apikey.c.profile_id,
    mcp_apikey.c.workspace_ref,
]


async def insert_apikey(
    conn: AsyncConnection,
    *,
    id: str,
    owner_login: str,
    token_hash: str,
    label: str,
    profile_id: str | None = None,
    workspace_ref: str | None = None,
) -> None:
    await conn.execute(
        insert(mcp_apikey).values(
            id=id,
            owner_login=owner_login,
            token_hash=token_hash,
            label=label,
            profile_id=profile_id,
            workspace_ref=workspace_ref,
        )
    )


async def set_apikey_profile(
    conn: AsyncConnection, owner_login: str, apikey_id: str, profile_id: str | None
) -> bool:
    q = (
        update(mcp_apikey)
        .where(mcp_apikey.c.id == apikey_id, mcp_apikey.c.owner_login == owner_login)
        .values(profile_id=profile_id)
        .returning(mcp_apikey.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def list_apikeys(conn: AsyncConnection, owner_login: str) -> list[dict[str, Any]]:
    last_used_subq = (
        select(
            mcp_audit_log.c.apikey_id,
            func.max(mcp_audit_log.c.ts).label("last_used_at"),
        )
        .group_by(mcp_audit_log.c.apikey_id)
        .subquery()
    )
    # profile_pinned : la clef workspace a une surcharge de profil persistante
    # (l'utilisateur a fixé un profil qui survivra à la rotation) vs suit le
    # défaut exposé. La jointure porte sur ws_id = workspace_ref de la clef.
    q = (
        select(
            *_APIKEY_COLS,
            last_used_subq.c.last_used_at,
            mcp_workspace_profile.c.ws_id.isnot(None).label("profile_pinned"),
        )
        .outerjoin(last_used_subq, mcp_apikey.c.id == last_used_subq.c.apikey_id)
        .outerjoin(
            mcp_workspace_profile,
            mcp_apikey.c.workspace_ref == mcp_workspace_profile.c.ws_id,
        )
        .where(mcp_apikey.c.owner_login == owner_login)
        .order_by(mcp_apikey.c.created_at)
    )
    return [dict(r) for r in (await conn.execute(q)).mappings().all()]


async def find_apikey_by_hash(conn: AsyncConnection, token_hash: str) -> dict[str, Any] | None:
    q = select(*_APIKEY_COLS).where(
        mcp_apikey.c.token_hash == token_hash,
        mcp_apikey.c.revoked.is_(False),
        # Token OAuth expiré → introuvable (deny-by-default). NULL = pas d'expiration.
        or_(mcp_apikey.c.expires_at.is_(None), mcp_apikey.c.expires_at > func.now()),
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def get_apikey(
    conn: AsyncConnection, owner_login: str, apikey_id: str
) -> dict[str, Any] | None:
    q = select(*_APIKEY_COLS).where(
        mcp_apikey.c.id == apikey_id,
        mcp_apikey.c.owner_login == owner_login,
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def revoke_apikey(conn: AsyncConnection, owner_login: str, apikey_id: str) -> bool:
    q = (
        update(mcp_apikey)
        .where(mcp_apikey.c.id == apikey_id, mcp_apikey.c.owner_login == owner_login)
        .values(revoked=True, revoked_at=func.coalesce(mcp_apikey.c.revoked_at, func.now()))
        .returning(mcp_apikey.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def expire_workspace_apikeys(
    conn: AsyncConnection,
    owner_login: str,
    workspace_ref: str,
    *,
    grace_seconds: int = WORKSPACE_KEY_ROTATION_GRACE_S,
) -> int:
    """Pose une échéance de grâce sur les clefs actives d'un workspace (rotation).

    Contrairement à `revoke_workspace_apikeys` (fail-closed immédiat : suppression
    de workspace, décochage de profil), la rotation laisse l'ancienne génération
    valide `grace_seconds` — la session agent en cours n'est pas coupée, la
    nouvelle clé est déjà dans les fichiers pour la prochaine. Ne RALLONGE jamais
    une échéance déjà plus proche. `find_apikey_by_hash` filtre sur `expires_at`.
    Retourne le nombre de clefs mises en grâce.

    L'échéance se calcule avec `now()` du SERVEUR, jamais avec l'horloge du
    portail : c'est le serveur qui juge l'expiration (`expires_at > now()`), et
    mélanger deux horloges fait dériver la fenêtre de grâce d'autant que leur
    écart — une clef posée « expirée maintenant » restait valide tant que la
    base retardait sur le portail (bug du test flaky grace=0, où la borne
    d'égalité n'était atteinte que si les deux horloges coïncidaient).
    """
    deadline = func.now() + timedelta(seconds=grace_seconds)
    q = (
        update(mcp_apikey)
        .where(
            mcp_apikey.c.owner_login == owner_login,
            mcp_apikey.c.workspace_ref == workspace_ref,
            mcp_apikey.c.revoked.is_(False),
            or_(mcp_apikey.c.expires_at.is_(None), mcp_apikey.c.expires_at > deadline),
        )
        .values(expires_at=deadline)
        .returning(mcp_apikey.c.id)
    )
    return len((await conn.execute(q)).all())


async def revoke_workspace_apikeys(
    conn: AsyncConnection, owner_login: str, workspace_ref: str
) -> int:
    """Spec 35 : révoque toutes les clefs actives d'un workspace. Retourne le nombre."""
    q = (
        update(mcp_apikey)
        .where(
            mcp_apikey.c.owner_login == owner_login,
            mcp_apikey.c.workspace_ref == workspace_ref,
            mcp_apikey.c.revoked.is_(False),
        )
        .values(revoked=True, revoked_at=func.coalesce(mcp_apikey.c.revoked_at, func.now()))
        .returning(mcp_apikey.c.id)
    )
    return len((await conn.execute(q)).all())


async def revoke_profile_workspace_apikeys(
    conn: AsyncConnection, owner_login: str, profile_id: str
) -> list[str]:
    """Spec 35 : révoque les clefs workspace dérivées d'un profil (fail closed au
    décochage). Retourne les ws_id affectés (pour régénérer leurs fichiers).
    Ne touche pas aux clefs personnelles (workspace_ref IS NULL)."""
    q = (
        update(mcp_apikey)
        .where(
            mcp_apikey.c.owner_login == owner_login,
            mcp_apikey.c.profile_id == profile_id,
            mcp_apikey.c.workspace_ref.isnot(None),
            mcp_apikey.c.revoked.is_(False),
        )
        .values(revoked=True, revoked_at=func.coalesce(mcp_apikey.c.revoked_at, func.now()))
        .returning(mcp_apikey.c.workspace_ref)
    )
    return sorted({row[0] for row in (await conn.execute(q)).all()})


async def delete_apikey(conn: AsyncConnection, owner_login: str, apikey_id: str) -> bool:
    q = (
        delete(mcp_apikey)
        .where(mcp_apikey.c.id == apikey_id, mcp_apikey.c.owner_login == owner_login)
        .returning(mcp_apikey.c.id)
    )
    return (await conn.execute(q)).first() is not None


async def purge_revoked_apikeys(
    conn: AsyncConnection, *, max_age_hours: int = REVOKED_APIKEY_RETENTION_HOURS
) -> int:
    """Supprime définitivement les clés révoquées OU expirées depuis `max_age_hours`.

    L'ancienneté se mesure à l'instant de révocation (`revoked_at`, COALESCE sur
    `created_at` pour les lignes d'avant la colonne) ou d'expiration (`expires_at`,
    clés en grâce de rotation — jamais revoked, elles s'accumuleraient sinon).
    Ne touche jamais une clé encore valide. Retourne le nombre de lignes supprimées.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    result = await conn.execute(
        delete(mcp_apikey).where(
            or_(
                and_(
                    mcp_apikey.c.revoked.is_(True),
                    func.coalesce(mcp_apikey.c.revoked_at, mcp_apikey.c.created_at) < cutoff,
                ),
                and_(
                    mcp_apikey.c.expires_at.isnot(None),
                    mcp_apikey.c.expires_at < cutoff,
                ),
            )
        )
    )
    return int(result.rowcount or 0)
