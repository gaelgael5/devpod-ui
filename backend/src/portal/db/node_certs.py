"""Persistance des certificats X.509 des nœuds Docker."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from .tables import node_certificates


async def save_node_cert_db(
    node_name: str,
    address: str,
    cert_pem: str,
    serial_number: str,
    signed_at: datetime,
    expires_at: datetime,
    conn: AsyncConnection,
) -> None:
    """Insère ou remplace le certificat d'un nœud (INSERT uniquement — pas de renouvellement)."""
    await conn.execute(
        insert(node_certificates).values(
            node_name=node_name,
            address=address,
            cert_pem=cert_pem,
            serial_number=serial_number,
            signed_at=signed_at,
            expires_at=expires_at,
            revoked_at=None,
        )
    )


async def get_node_cert_db(
    node_name: str, conn: AsyncConnection
) -> dict[str, Any] | None:
    row = (
        await conn.execute(
            select(node_certificates).where(node_certificates.c.node_name == node_name)
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def revoke_node_cert_db(node_name: str, conn: AsyncConnection) -> None:
    await conn.execute(
        update(node_certificates)
        .where(node_certificates.c.node_name == node_name)
        .values(revoked_at=__import__("sqlalchemy").func.now())
    )


async def list_expiring_certs_db(
    conn: AsyncConnection, within_days: int = 30
) -> list[dict[str, Any]]:
    """Retourne les certs non révoqués qui expirent dans les prochains N jours."""
    from sqlalchemy import func, text

    rows = (
        await conn.execute(
            select(node_certificates)
            .where(node_certificates.c.revoked_at.is_(None))
            .where(
                node_certificates.c.expires_at
                <= func.now() + text(f"interval '{within_days} days'")
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]
