"""Accès en base aux profils de host.

Un profil de host choisit un profil de machine et value les variables déclarées
par le type d'hyperviseur — dont la capacité en workspaces.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import HostProfile
from .tables import host_profiles


def _row_to_profile(row: dict[str, Any]) -> HostProfile:
    return HostProfile.model_validate(
        {
            "slug": row["slug"],
            "label": row["label"],
            "machine_profile": row["machine_profile"],
            "variables": row["variables"] or {},
        }
    )


async def list_host_profiles(
    conn: AsyncConnection, *, machine_profile: str | None = None
) -> list[HostProfile]:
    """Profils de host, triés par label — c'est ce que l'œil lit."""
    stmt = select(host_profiles)
    if machine_profile is not None:
        stmt = stmt.where(host_profiles.c.machine_profile == machine_profile)
    rows = (await conn.execute(stmt.order_by(host_profiles.c.label))).mappings().all()
    return [_row_to_profile(dict(r)) for r in rows]


async def get_host_profile(slug: str, conn: AsyncConnection) -> HostProfile | None:
    row = (
        (await conn.execute(select(host_profiles).where(host_profiles.c.slug == slug)))
        .mappings()
        .first()
    )
    return _row_to_profile(dict(row)) if row else None


async def upsert_host_profile(profile: HostProfile, conn: AsyncConnection) -> None:
    """Crée ou remplace. Le slug est l'identité : le renommer, c'est un autre profil."""
    requete = select(host_profiles.c.slug).where(host_profiles.c.slug == profile.slug)
    existe = (await conn.execute(requete)).scalar_one_or_none()
    vals: dict[str, Any] = {
        "slug": profile.slug,
        "label": profile.label,
        "machine_profile": profile.machine_profile,
        "variables": dict(profile.variables),
    }
    if existe is None:
        await conn.execute(insert(host_profiles).values(**vals))
        return
    vals.pop("slug")
    vals["updated_at"] = func.now()
    await conn.execute(
        update(host_profiles).where(host_profiles.c.slug == profile.slug).values(**vals)
    )


async def delete_host_profile(slug: str, conn: AsyncConnection) -> bool:
    """`True` si un profil a bien été supprimé."""
    res = await conn.execute(delete(host_profiles).where(host_profiles.c.slug == slug))
    return bool(res.rowcount)
