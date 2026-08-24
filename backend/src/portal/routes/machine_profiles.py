"""Profils de machine : CRUD admin, lecture pour la création.

Un profil fige les paramètres de création d'une machine et les recettes à y
poser. Il remplace le jeu unique `test_host_params` du type d'hyperviseur.

Deux publics, deux gardes : l'administration des profils est réservée aux
administrateurs — c'est elle qui décide ce qu'on installe et avec quels droits
— tandis que la LECTURE est ouverte à tout utilisateur, puisque c'est lui qui
choisira son profil au moment de créer sa machine.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin, require_user
from ..config.models import MachineProfile
from ..config.store import load_global
from ..db.engine import get_conn
from ..db.machine_profiles import delete_profile, get_profile, list_profiles, upsert_profile

router = APIRouter(tags=["machine-profiles"])
me_router = APIRouter(tags=["machine-profiles"])
log = structlog.get_logger(__name__)


def _require_known_type(hypervisor_type: str) -> None:
    """Un profil qui vise un type inexistant serait inapplicable, et le dirait
    seulement au moment de créer une machine."""
    cfg = load_global()
    if not any(t.name == hypervisor_type for t in cfg.hypervisor_types):
        connus = ", ".join(sorted(t.name for t in cfg.hypervisor_types)) or "aucun"
        raise HTTPException(
            status_code=422,
            detail=f"Type d'hyperviseur {hypervisor_type!r} inconnu — connus : {connus}",
        )


@router.get("/machine-profiles")
async def admin_list_profiles(
    machine_type: str | None = None,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    profils = await list_profiles(conn, machine_type=machine_type)
    return [p.model_dump() for p in profils]


@router.put("/machine-profiles/{slug}")
async def admin_save_profile(
    slug: str,
    body: MachineProfile,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Crée ou remplace. Le slug de l'URL fait foi : le corps ne peut pas en
    désigner un autre, sans quoi un PUT écraserait un profil voisin."""
    if body.slug != slug:
        raise HTTPException(
            status_code=422,
            detail=f"slug du corps ({body.slug!r}) différent de celui de l'URL ({slug!r})",
        )
    _require_known_type(body.hypervisor_type)
    await upsert_profile(body, conn)
    log.info("machine_profile_saved", slug=slug, actor=user.login)
    return body.model_dump()


@router.delete("/machine-profiles/{slug}", status_code=204)
async def admin_delete_profile(
    slug: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    if not await delete_profile(slug, conn):
        raise HTTPException(status_code=404, detail=f"Profil {slug!r} introuvable")
    log.info("machine_profile_deleted", slug=slug, actor=user.login)


@me_router.get("/machine-profiles")
async def my_usable_profiles(
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Profils proposables à la création d'une machine de test.

    Restreint à `machine_type=test` : créer une machine de ressources n'existe
    pas encore côté application — on la crée à la main, puis on saisit sa
    connexion. Exposer ces profils ici promettrait une action qui n'existe pas.
    """
    profils = await list_profiles(conn, machine_type="test")
    return [
        {
            "slug": p.slug,
            "label": p.label,
            "hypervisor_type": p.hypervisor_type,
            # Le detail des params ne regarde pas l'utilisateur : ils sont figes
            # par l'administrateur. On expose ce qui l'aide a choisir.
            "recipes": [r.key for r in p.recipes],
        }
        for p in profils
    ]


async def resolve_profile(slug: str, conn: AsyncConnection) -> MachineProfile:
    """Profil d'un slug, ou 404. Point d'entrée commun à la création."""
    profil = await get_profile(slug, conn)
    if profil is None:
        raise HTTPException(status_code=404, detail=f"Profil {slug!r} introuvable")
    return profil
