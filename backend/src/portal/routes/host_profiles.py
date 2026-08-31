"""Profils de host : CRUD admin, et lecture des variables à renseigner.

Un profil de host choisit un profil de machine et VALUE les variables déclarées
par le type d'hyperviseur de ce profil. C'est là que vit `capacity_workspaces` :
le profil de machine sait construire la VM, il ne sait pas combien de workspaces
elle tient sans planter — seul l'exploitant le sait.

Réservé aux administrateurs : ces profils décident de ce qu'un forfait
provisionne, donc de ce qui est facturé.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..config.models import HostProfile, HypervisorVariable, MachineProfile
from ..config.store import load_global
from ..db.billing_offers import offres_utilisant_profil
from ..db.engine import get_conn
from ..db.host_profiles import (
    delete_host_profile,
    get_host_profile,
    list_host_profiles,
    upsert_host_profile,
)
from ..db.machine_profiles import get_profile

router = APIRouter(tags=["host-profiles"])
log = structlog.get_logger(__name__)


def _variables_declarees(machine: MachineProfile) -> list[HypervisorVariable]:
    """Variables que ce profil de machine impose de renseigner.

    Elles viennent du TYPE d'hyperviseur, pas du profil de machine : c'est le
    type qui sait quelles grandeurs ont un sens pour ses machines.
    """
    cfg = load_global()
    for t in cfg.hypervisor_types:
        if t.name == machine.hypervisor_type:
            return list(t.variables)
    raise HTTPException(
        status_code=422,
        detail=(
            f"Le profil de machine {machine.slug!r} vise le type "
            f"{machine.hypervisor_type!r}, qui n'existe plus"
        ),
    )


def _valider_variables(
    valeurs: dict[str, str], declarees: list[HypervisorVariable]
) -> dict[str, str]:
    """Valeurs acceptables, ou 422 nommant la variable fautive.

    Deux refus, tous deux au moment de la saisie plutôt qu'à la création de la
    machine : une variable qui n'est pas déclarée (faute de frappe, variable
    retirée du type), et une valeur qui ne respecte pas le type déclaré.
    """
    par_slug = {v.slug: v for v in declarees}
    inconnues = sorted(set(valeurs) - set(par_slug))
    if inconnues:
        connues = ", ".join(sorted(par_slug)) or "aucune"
        raise HTTPException(
            status_code=422,
            detail=(
                f"Variables non déclarées par le type : {', '.join(inconnues)} — "
                f"déclarées : {connues}"
            ),
        )

    propres: dict[str, str] = {}
    for slug, brut in valeurs.items():
        try:
            propres[slug] = par_slug[slug].valider_valeur(brut)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return propres


async def _machine_ou_422(slug: str, conn: AsyncConnection) -> MachineProfile:
    machine = await get_profile(slug, conn)
    if machine is None:
        raise HTTPException(status_code=422, detail=f"Profil de machine {slug!r} introuvable")
    return machine


@router.get("/host-profiles")
async def admin_list_host_profiles(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    profils = await list_host_profiles(conn)
    return [p.model_dump() for p in profils]


@router.get("/host-profiles/variables/{machine_profile}")
async def admin_host_profile_variables(
    machine_profile: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Variables à renseigner pour ce profil de machine.

    L'IHM l'appelle quand l'admin choisit un profil de machine : le formulaire
    se construit à partir de la déclaration, il n'est pas figé dans le code.
    """
    machine = await _machine_ou_422(machine_profile, conn)
    return [v.model_dump() for v in _variables_declarees(machine)]


@router.put("/host-profiles/{slug}")
async def admin_save_host_profile(
    slug: str,
    body: HostProfile,
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
    machine = await _machine_ou_422(body.machine_profile, conn)
    propre = body.model_copy(
        update={"variables": _valider_variables(body.variables, _variables_declarees(machine))}
    )
    await upsert_host_profile(propre, conn)
    log.info("host_profile_saved", slug=slug, actor=user.login)
    return propre.model_dump()


@router.delete("/host-profiles/{slug}", status_code=204)
async def admin_delete_host_profile(
    slug: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> None:
    # Une offre qui déclare ce profil deviendrait improvisionnable en silence :
    # le refus nomme les offres, sans quoi il faudrait les chercher à la main.
    offres = await offres_utilisant_profil(slug, conn)
    if offres:
        sujet = "les offres" if len(offres) > 1 else "l'offre"
        raise HTTPException(
            status_code=409,
            detail=(
                f"Profil de host {slug!r} utilisé par {sujet} {', '.join(offres)} — "
                "retirez-le d'abord de leur onglet « Profils de host »"
            ),
        )
    if not await delete_host_profile(slug, conn):
        raise HTTPException(status_code=404, detail=f"Profil de host {slug!r} introuvable")
    log.info("host_profile_deleted", slug=slug, actor=user.login)


@router.get("/host-profiles/{slug}")
async def admin_get_host_profile(
    slug: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    profil = await get_host_profile(slug, conn)
    if profil is None:
        raise HTTPException(status_code=404, detail=f"Profil de host {slug!r} introuvable")
    return profil.model_dump()
