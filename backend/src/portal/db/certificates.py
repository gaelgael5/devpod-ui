from __future__ import annotations

from typing import Any

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import harpo_certificates


async def create_certificate(
    login: str,
    slug: str,
    label: str,
    description: str,
    cert_type: str,
    public_key: str,
    *,
    private_key_local: bytes | None,
    private_key_vault_ref: str | None,
    storage_type: str,
    vault_identifier: str | None,
    conn: AsyncConnection,
) -> None:
    await conn.execute(
        insert(harpo_certificates).values(
            owner_login=login,
            slug=slug,
            label=label,
            description=description,
            cert_type=cert_type,
            public_key=public_key,
            private_key_local=private_key_local,
            private_key_vault_ref=private_key_vault_ref,
            storage_type=storage_type,
            vault_identifier=vault_identifier,
        )
    )


_PUBLIC_COLS = [
    harpo_certificates.c.slug,
    harpo_certificates.c.label,
    harpo_certificates.c.description,
    harpo_certificates.c.cert_type,
    harpo_certificates.c.public_key,
    harpo_certificates.c.storage_type,
    harpo_certificates.c.vault_identifier,
    harpo_certificates.c.owner_login,
    harpo_certificates.c.is_public,
    harpo_certificates.c.created_at,
]


async def list_certificates(login: str, conn: AsyncConnection) -> list[dict[str, Any]]:
    q = select(*_PUBLIC_COLS).where(
        or_(
            harpo_certificates.c.owner_login == login,
            harpo_certificates.c.is_public.is_(True),
        )
    ).order_by(harpo_certificates.c.created_at)
    rows = (await conn.execute(q)).mappings().all()
    return [{**dict(r), "is_own": r["owner_login"] == login} for r in rows]


async def get_certificate(login: str, slug: str, conn: AsyncConnection) -> dict[str, Any] | None:
    q = select(*_PUBLIC_COLS).where(
        harpo_certificates.c.slug == slug,
        or_(
            harpo_certificates.c.owner_login == login,
            harpo_certificates.c.is_public.is_(True),
        ),
    )
    row = (await conn.execute(q)).mappings().first()
    if row is None:
        return None
    return {**dict(row), "is_own": row["owner_login"] == login}


async def get_private_key_local(login: str, slug: str, conn: AsyncConnection) -> bytes | None:
    """Retourne private_key_local uniquement si l'utilisateur est le propriétaire."""
    q = select(harpo_certificates.c.private_key_local).where(
        harpo_certificates.c.slug == slug,
        harpo_certificates.c.owner_login == login,
    )
    row = (await conn.execute(q)).first()
    return row[0] if row else None


async def delete_certificate(
    login: str, slug: str, conn: AsyncConnection
) -> dict[str, Any] | None:
    q = (
        delete(harpo_certificates)
        .where(
            harpo_certificates.c.owner_login == login,
            harpo_certificates.c.slug == slug,
        )
        .returning(*_PUBLIC_COLS, harpo_certificates.c.private_key_vault_ref)
    )
    row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def set_public(
    owner_login: str, slug: str, is_public: bool, conn: AsyncConnection
) -> bool:
    q = (
        update(harpo_certificates)
        .where(
            harpo_certificates.c.owner_login == owner_login,
            harpo_certificates.c.slug == slug,
        )
        .values(is_public=is_public)
        .returning(harpo_certificates.c.slug)
    )
    row = (await conn.execute(q)).first()
    return row is not None


async def update_certificate(
    login: str,
    slug: str,
    *,
    label: str,
    description: str,
    public_key: str | None,
    private_key_local: bytes | None,
    private_key_vault_ref: str | None,
    conn: AsyncConnection,
) -> bool:
    values: dict[str, Any] = {"label": label, "description": description}
    if public_key is not None:
        values["public_key"] = public_key
    if private_key_local is not None:
        values["private_key_local"] = private_key_local
        values["private_key_vault_ref"] = None
    elif private_key_vault_ref is not None:
        values["private_key_vault_ref"] = private_key_vault_ref
        values["private_key_local"] = None
    q = (
        update(harpo_certificates)
        .where(
            harpo_certificates.c.owner_login == login,
            harpo_certificates.c.slug == slug,
        )
        .values(**values)
        .returning(harpo_certificates.c.slug)
    )
    row = (await conn.execute(q)).first()
    return row is not None
