from __future__ import annotations

from typing import Any

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import harpo_secrets

_PUBLIC_COLS = [
    harpo_secrets.c.slug,
    harpo_secrets.c.label,
    harpo_secrets.c.description,
    harpo_secrets.c.secret_type,
    harpo_secrets.c.secret_value_vault_ref,
    harpo_secrets.c.storage_type,
    harpo_secrets.c.vault_identifier,
    harpo_secrets.c.owner_login,
    harpo_secrets.c.is_public,
    harpo_secrets.c.created_at,
]


async def create_secret(
    owner_login: str,
    slug: str,
    label: str,
    description: str,
    secret_type: str,
    *,
    secret_value_local: bytes | None,
    secret_value_vault_ref: str | None,
    storage_type: str,
    vault_identifier: str | None,
    conn: AsyncConnection,
) -> None:
    await conn.execute(
        insert(harpo_secrets).values(
            owner_login=owner_login,
            slug=slug,
            label=label,
            description=description,
            secret_type=secret_type,
            secret_value_local=secret_value_local,
            secret_value_vault_ref=secret_value_vault_ref,
            storage_type=storage_type,
            vault_identifier=vault_identifier,
        )
    )


def _with_is_own(rows: list[Any], login: str) -> list[dict[str, Any]]:
    return [{**dict(r), "is_own": r["owner_login"] == login} for r in rows]


async def list_secrets(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    q = (
        select(*_PUBLIC_COLS)
        .where(
            or_(
                harpo_secrets.c.owner_login == login,
                harpo_secrets.c.is_public.is_(True),
            )
        )
        .order_by(harpo_secrets.c.created_at)
    )
    rows = (await conn.execute(q)).mappings().all()
    return _with_is_own(list(rows), login)


async def list_secrets_by_type(
    login: str, secret_type: str, conn: AsyncConnection
) -> list[dict[str, Any]]:
    q = (
        select(*_PUBLIC_COLS)
        .where(
            harpo_secrets.c.secret_type == secret_type,
            or_(
                harpo_secrets.c.owner_login == login,
                harpo_secrets.c.is_public.is_(True),
            ),
        )
        .order_by(harpo_secrets.c.created_at)
    )
    rows = (await conn.execute(q)).mappings().all()
    return _with_is_own(list(rows), login)


async def get_secret(
    login: str, slug: str, conn: AsyncConnection
) -> dict[str, Any] | None:
    q = select(*_PUBLIC_COLS).where(
        harpo_secrets.c.slug == slug,
        or_(
            harpo_secrets.c.owner_login == login,
            harpo_secrets.c.is_public.is_(True),
        ),
    )
    row = (await conn.execute(q)).mappings().first()
    if row is None:
        return None
    return {**dict(row), "is_own": row["owner_login"] == login}


async def get_secret_value_local(
    login: str, slug: str, conn: AsyncConnection
) -> bytes | None:
    """Retourne secret_value_local uniquement si l'utilisateur est le propriétaire."""
    q = select(harpo_secrets.c.secret_value_local).where(
        harpo_secrets.c.slug == slug,
        harpo_secrets.c.owner_login == login,
    )
    row = (await conn.execute(q)).first()
    return row[0] if row else None


async def update_secret(
    login: str,
    slug: str,
    *,
    label: str,
    description: str,
    secret_value_local: bytes | None,
    secret_value_vault_ref: str | None,
    conn: AsyncConnection,
) -> bool:
    """Met à jour le label, la description et la valeur du secret.

    Si secret_value_local n'est pas None → secret_value_vault_ref est effacé.
    Si secret_value_vault_ref n'est pas None → secret_value_local est effacé.
    Scopé à (owner_login == login, slug).
    """
    values: dict[str, Any] = {"label": label, "description": description}
    if secret_value_local is not None:
        values["secret_value_local"] = secret_value_local
        values["secret_value_vault_ref"] = None
    elif secret_value_vault_ref is not None:
        values["secret_value_vault_ref"] = secret_value_vault_ref
        values["secret_value_local"] = None

    q = (
        update(harpo_secrets)
        .where(
            harpo_secrets.c.owner_login == login,
            harpo_secrets.c.slug == slug,
        )
        .values(**values)
        .returning(harpo_secrets.c.slug)
    )
    row = (await conn.execute(q)).first()
    return row is not None


async def delete_secret(
    login: str, slug: str, conn: AsyncConnection
) -> dict[str, Any] | None:
    """Supprime le secret et retourne la row complète (y compris secret_value_vault_ref)."""
    q = (
        delete(harpo_secrets)
        .where(
            harpo_secrets.c.owner_login == login,
            harpo_secrets.c.slug == slug,
        )
        .returning(*_PUBLIC_COLS)
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def set_secret_public(
    owner_login: str, slug: str, is_public: bool, conn: AsyncConnection
) -> bool:
    """Marque le secret comme public ou privé. Scopé à (owner_login, slug) pour prévenir l'IDOR."""
    q = (
        update(harpo_secrets)
        .where(
            harpo_secrets.c.owner_login == owner_login,
            harpo_secrets.c.slug == slug,
        )
        .values(is_public=is_public)
        .returning(harpo_secrets.c.slug)
    )
    row = (await conn.execute(q)).first()
    return row is not None
