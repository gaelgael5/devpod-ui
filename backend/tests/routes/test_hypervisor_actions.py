"""Exécution d'une action déclarée par un type d'hyperviseur.

Deux familles, deux points de déclenchement, et un garde-fou commun : une
action ne s'exécute que là où sa cible dit qu'elle s'applique.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from portal.config.models import (
    AuthConfig,
    GlobalConfig,
    HostConfig,
    Hypervisor,
    HypervisorAction,
    HypervisorType,
    OidcConfig,
    ServerConfig,
)
from portal.routes.hypervisor_actions import (
    ExecuteRequest,
    execute_host_action,
    execute_hypervisor_action,
    list_host_actions,
    list_hypervisor_actions,
)

# Les placeholders du descripteur sont de la forme `{CLE}` (cf. `_substitute`).
_SPEC = {"commands": ["qm set {VMID} --memory 2048", "echo {PORTAL_TOKEN}"]}


def _cfg(*, hosts: list[HostConfig] | None = None) -> GlobalConfig:
    hyp_type = HypervisorType(
        name="proxmox4vm",
        actions=[
            HypervisorAction(
                label="Increase memory +1G",
                slug="proxmox4vm-increase-memory-1g",
                script="https://raw.example.com/mem.json",
                cible="machine",
            ),
            HypervisorAction(
                label="Inventaire",
                slug="proxmox4vm-inventaire",
                script="https://raw.example.com/inv.json",
                cible="hyperviseur",
            ),
        ],
    )
    node = Hypervisor(
        name="pve1",
        address="192.168.10.41",
        ssh_key_path="/data/keys/pve1",
        pve_node="pve",
        hypervisor_type="proxmox4vm",
    )
    return GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url="https://portal.example.com"),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hypervisor_types=[hyp_type],
        hypervisors=[node],
        hosts=hosts or [],
    )


def _host_sur_pve() -> HostConfig:
    return HostConfig(name="host-105-1", type="ssh", proxmox_node="pve1", vmid="105")


def _host_enrole_a_la_main() -> HostConfig:
    return HostConfig(name="rag", type="ssh", address="192.168.10.184")


class _User:
    login = "admin"


# ─── Listing ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_liste_hyperviseur_ne_rend_que_les_actions_hyperviseur() -> None:
    with patch("portal.routes.hypervisor_actions.load_global", return_value=_cfg()):
        actions = await list_hypervisor_actions("pve1", user=_User())

    assert [a.slug for a in actions] == ["proxmox4vm-inventaire"]


@pytest.mark.asyncio
async def test_liste_host_ne_rend_que_les_actions_machine() -> None:
    cfg = _cfg(hosts=[_host_sur_pve()])
    with patch("portal.routes.hypervisor_actions.load_global", return_value=cfg):
        actions = await list_host_actions("host-105-1", user=_User())

    assert [a.slug for a in actions] == ["proxmox4vm-increase-memory-1g"]


@pytest.mark.asyncio
async def test_liste_vide_pour_un_host_sans_hyperviseur() -> None:
    """L'IHM interroge toutes les lignes : une erreur ne lui apprendrait rien."""
    cfg = _cfg(hosts=[_host_enrole_a_la_main()])
    with patch("portal.routes.hypervisor_actions.load_global", return_value=cfg):
        assert await list_host_actions("rag", user=_User()) == []


# ─── Garde-fous de cible ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_action_machine_refusee_sur_la_page_hyperviseurs() -> None:
    """Sans ce refus, le script recevrait un VMID vide et tournerait sur l'hôte."""
    with (
        patch("portal.routes.hypervisor_actions.load_global", return_value=_cfg()),
        pytest.raises(HTTPException) as exc,
    ):
        await execute_hypervisor_action(
            "pve1",
            "proxmox4vm-increase-memory-1g",
            ExecuteRequest(args={}),
            user=_User(),
        )
    assert exc.value.status_code == 422
    assert "machine" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_action_hyperviseur_refusee_sur_la_ligne_d_un_noeud() -> None:
    cfg = _cfg(hosts=[_host_sur_pve()])
    with (
        patch("portal.routes.hypervisor_actions.load_global", return_value=cfg),
        pytest.raises(HTTPException) as exc,
    ):
        await execute_host_action(
            "host-105-1",
            "proxmox4vm-inventaire",
            ExecuteRequest(args={}),
            user=_User(),
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_action_inconnue_rend_404() -> None:
    with (
        patch("portal.routes.hypervisor_actions.load_global", return_value=_cfg()),
        pytest.raises(HTTPException) as exc,
    ):
        await execute_hypervisor_action(
            "pve1", "proxmox4vm-inexistante", ExecuteRequest(args={}), user=_User()
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_host_sans_hyperviseur_rend_409() -> None:
    """Le host existe : c'est l'action qui n'a pas de sens, pas la ressource."""
    cfg = _cfg(hosts=[_host_enrole_a_la_main()])
    with (
        patch("portal.routes.hypervisor_actions.load_global", return_value=cfg),
        pytest.raises(HTTPException) as exc,
    ):
        await execute_host_action(
            "rag",
            "proxmox4vm-increase-memory-1g",
            ExecuteRequest(args={}),
            user=_User(),
        )
    assert exc.value.status_code == 409


# ─── Substitution et exécution ────────────────────────────────────────────────


def _commandes_streamees(mock_stream: AsyncMock) -> list[str]:
    return mock_stream.call_args.args[1]


@pytest.mark.asyncio
async def test_action_machine_substitue_le_vmid_du_host() -> None:
    """Le VMID vient du host, pas du formulaire : on agit sur CETTE machine."""
    cfg = _cfg(hosts=[_host_sur_pve()])

    async def _fake_stream(node, commands):  # noqa: ANN001, ANN202
        yield b""

    with (
        patch("portal.routes.hypervisor_actions.load_global", return_value=cfg),
        patch(
            "portal.routes.hypervisor_actions.fetch_script_spec",
            AsyncMock(return_value=dict(_SPEC)),
        ),
        patch("portal.routes.hypervisor_actions._ssh_stream", side_effect=_fake_stream) as ssh,
    ):
        resp = await execute_host_action(
            "host-105-1",
            "proxmox4vm-increase-memory-1g",
            ExecuteRequest(args={"VMID": "999"}),
            user=_User(),
        )
        # Le corps n'est construit qu'à la consommation du flux.
        [chunk async for chunk in resp.body_iterator]

    assert _commandes_streamees(ssh)[0] == "qm set 105 --memory 2048"


@pytest.mark.asyncio
async def test_le_token_portail_est_masque_dans_l_echo_des_commandes() -> None:
    cfg = _cfg(hosts=[_host_sur_pve()])

    async def _fake_stream(node, commands):  # noqa: ANN001, ANN202
        yield b"ok\n"

    with (
        patch("portal.routes.hypervisor_actions.load_global", return_value=cfg),
        patch(
            "portal.routes.hypervisor_actions.fetch_script_spec",
            AsyncMock(return_value=dict(_SPEC)),
        ),
        patch("portal.routes.hypervisor_actions._ssh_stream", side_effect=_fake_stream) as ssh,
    ):
        resp = await execute_host_action(
            "host-105-1",
            "proxmox4vm-increase-memory-1g",
            ExecuteRequest(args={}),
            user=_User(),
        )
        corps = b"".join([chunk async for chunk in resp.body_iterator]).decode()

    token = _commandes_streamees(ssh)[1].removeprefix("echo ")
    # `_substitute` passe les valeurs par shlex.quote : le masque aussi.
    assert "echo '***'" in corps
    # Le token réel part bien en SSH, mais jamais dans ce qui s'affiche.
    assert token not in corps
