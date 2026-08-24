"""Accès en base aux profils de machine.

Un profil fige les paramètres de création d'une machine et les recettes à y
poser. Il remplace le jeu unique `test_host_params` que portait le type
d'hyperviseur — lequel n'autorisait qu'un seul modèle de machine par type.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import MachineProfile
from .tables import machine_profiles


def _row_to_profile(row: dict[str, Any]) -> MachineProfile:
    return MachineProfile.model_validate(
        {
            "slug": row["slug"],
            "label": row["label"],
            "machine_type": row["machine_type"],
            "hypervisor_type": row["hypervisor_type"],
            "params": row["params"] or {},
            "recipes": row["recipes"] or [],
            "services": row["services"] or [],
        }
    )


def _to_values(profile: MachineProfile) -> dict[str, Any]:
    return {
        "slug": profile.slug,
        "label": profile.label,
        "machine_type": profile.machine_type,
        "hypervisor_type": profile.hypervisor_type,
        "params": dict(profile.params),
        "recipes": [r.model_dump() for r in profile.recipes],
        "services": [s.model_dump() for s in profile.services],
    }


async def list_profiles(
    conn: AsyncConnection,
    *,
    machine_type: str | None = None,
    hypervisor_type: str | None = None,
) -> list[MachineProfile]:
    """Profils, filtrés au besoin. Triés par label — c'est ce que l'œil lit."""
    stmt = select(machine_profiles)
    if machine_type is not None:
        stmt = stmt.where(machine_profiles.c.machine_type == machine_type)
    if hypervisor_type is not None:
        stmt = stmt.where(machine_profiles.c.hypervisor_type == hypervisor_type)
    rows = (await conn.execute(stmt.order_by(machine_profiles.c.label))).mappings().all()
    return [_row_to_profile(dict(r)) for r in rows]


async def get_profile(slug: str, conn: AsyncConnection) -> MachineProfile | None:
    row = (
        (await conn.execute(select(machine_profiles).where(machine_profiles.c.slug == slug)))
        .mappings()
        .first()
    )
    return _row_to_profile(dict(row)) if row else None


async def upsert_profile(profile: MachineProfile, conn: AsyncConnection) -> None:
    """Crée ou remplace. Le slug est l'identité : le renommer, c'est un autre profil."""
    requete = select(machine_profiles.c.slug).where(machine_profiles.c.slug == profile.slug)
    existe = (await conn.execute(requete)).scalar_one_or_none()
    vals = _to_values(profile)
    if existe is None:
        await conn.execute(insert(machine_profiles).values(**vals))
        return
    vals.pop("slug")
    vals["updated_at"] = func.now()
    await conn.execute(
        update(machine_profiles).where(machine_profiles.c.slug == profile.slug).values(**vals)
    )


async def delete_profile(slug: str, conn: AsyncConnection) -> bool:
    """`True` si un profil a bien été supprimé.

    Les machines déjà créées gardent leur `profile_slug` : la référence devient
    pendante, et c'est voulu — savoir avec quel profil une machine a été montée
    reste utile même si ce profil n'existe plus.
    """
    res = await conn.execute(delete(machine_profiles).where(machine_profiles.c.slug == slug))
    return bool(res.rowcount)
