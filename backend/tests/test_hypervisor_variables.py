"""Variables déclarées par un type d'hyperviseur — persistance.

Le type d'hyperviseur dit CE QUI EXISTE, le profil de host dit COMBIEN. Si la
déclaration ne survit pas à l'enregistrement, le profil de host n'a plus rien à
renseigner : l'écran affiche « ce type ne déclare aucune variable » et
`capacity_workspaces` devient introuvable — donc un forfait ne sait plus combien
de workspaces sa machine tient.

Régression constatée en recette le 27/08/2026 : `HypervisorTypeRequest` ne
déclarait pas le champ, pydantic l'ignorait en silence, et le handler
reconstruisait un `HypervisorType` sans lui. Aucune erreur, aucune donnée.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

CAPACITE = {"label": "Capacité en workspaces", "slug": "capacity_workspaces", "type": "int"}
ZONE = {"label": "Zone", "slug": "zone", "type": "string"}


def _cfg(types):
    from portal.config.models import AuthConfig, GlobalConfig, OidcConfig, ServerConfig

    return GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hypervisor_types=types,
    )


def _admin():
    from portal.auth.rbac import UserInfo

    return UserInfo(login="admin", roles=["admin"])


@pytest.mark.asyncio
async def test_ajout_conserve_les_variables_declarees() -> None:
    from portal.routes.proxmox import HypervisorTypeRequest, add_hypervisor_type

    cfg = _cfg([])
    with (
        patch("portal.routes.proxmox.load_global", return_value=cfg),
        patch("portal.routes.proxmox.save_global", new_callable=AsyncMock),
    ):
        await add_hypervisor_type(
            HypervisorTypeRequest(name="proxmox4vm", label="Proxmox 4 VM", variables=[CAPACITE]),
            user=_admin(),
        )

    assert [v.slug for v in cfg.hypervisor_types[0].variables] == ["capacity_workspaces"]


@pytest.mark.asyncio
async def test_mise_a_jour_conserve_les_variables_declarees() -> None:
    from portal.config.models import HypervisorType
    from portal.routes.proxmox import HypervisorTypeRequest, update_hypervisor_type

    cfg = _cfg([HypervisorType(name="proxmox4vm")])
    with (
        patch("portal.routes.proxmox.load_global", return_value=cfg),
        patch("portal.routes.proxmox.save_global", new_callable=AsyncMock),
    ):
        await update_hypervisor_type(
            "proxmox4vm",
            HypervisorTypeRequest(name="proxmox4vm", variables=[CAPACITE, ZONE]),
            user=_admin(),
        )

    assert [v.slug for v in cfg.hypervisor_types[0].variables] == ["capacity_workspaces", "zone"]


@pytest.mark.asyncio
async def test_le_type_declare_de_la_variable_survit() -> None:
    # Un `int` rendu en `string` ferait accepter « beaucoup » comme capacité.
    from portal.routes.proxmox import HypervisorTypeRequest, add_hypervisor_type

    cfg = _cfg([])
    with (
        patch("portal.routes.proxmox.load_global", return_value=cfg),
        patch("portal.routes.proxmox.save_global", new_callable=AsyncMock),
    ):
        await add_hypervisor_type(
            HypervisorTypeRequest(name="proxmox4vm", variables=[CAPACITE]),
            user=_admin(),
        )

    assert cfg.hypervisor_types[0].variables[0].type == "int"


@pytest.mark.asyncio
async def test_mise_a_jour_remplace_la_declaration() -> None:
    # Le corps décrit l'état voulu, pas un delta : une variable retirée doit
    # disparaître, sans quoi un profil de host continuerait à la réclamer.
    from portal.config.models import HypervisorType
    from portal.routes.proxmox import HypervisorTypeRequest, update_hypervisor_type

    cfg = _cfg([HypervisorType(name="proxmox4vm", variables=[CAPACITE, ZONE])])
    with (
        patch("portal.routes.proxmox.load_global", return_value=cfg),
        patch("portal.routes.proxmox.save_global", new_callable=AsyncMock),
    ):
        await update_hypervisor_type(
            "proxmox4vm",
            HypervisorTypeRequest(name="proxmox4vm", variables=[CAPACITE]),
            user=_admin(),
        )

    assert [v.slug for v in cfg.hypervisor_types[0].variables] == ["capacity_workspaces"]


@pytest.mark.asyncio
async def test_refuse_deux_variables_de_meme_slug() -> None:
    # Deux variables de même slug rendraient la valeur retenue dépendante de
    # l'ordre de saisie. Refus explicite en 422, pas une 500 pydantic.
    from portal.routes.proxmox import HypervisorTypeRequest, add_hypervisor_type

    cfg = _cfg([])
    with (
        patch("portal.routes.proxmox.load_global", return_value=cfg),
        patch("portal.routes.proxmox.save_global", new_callable=AsyncMock),
        pytest.raises(HTTPException) as exc,
    ):
        await add_hypervisor_type(
            HypervisorTypeRequest(name="proxmox4vm", variables=[CAPACITE, CAPACITE]),
            user=_admin(),
        )

    assert exc.value.status_code == 422
    assert "capacity_workspaces" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_les_parametres_de_host_de_test_restent_preserves() -> None:
    # Garde-fou de voisinage : `test_host_params` se règle par une autre route,
    # une mise à jour du type ne doit pas l'effacer au passage.
    from portal.config.models import HypervisorType
    from portal.routes.proxmox import HypervisorTypeRequest, update_hypervisor_type

    cfg = _cfg([HypervisorType(name="proxmox4vm", test_host_params={"MEMORY": "2048"})])
    with (
        patch("portal.routes.proxmox.load_global", return_value=cfg),
        patch("portal.routes.proxmox.save_global", new_callable=AsyncMock),
    ):
        await update_hypervisor_type(
            "proxmox4vm",
            HypervisorTypeRequest(name="proxmox4vm", variables=[CAPACITE]),
            user=_admin(),
        )

    assert cfg.hypervisor_types[0].test_host_params == {"MEMORY": "2048"}
