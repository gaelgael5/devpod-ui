"""Bug 023 : add_script/destroy_script fetchés sans contrôle SSRF ni
follow_redirects=False, alors que le JSON récupéré est ensuite exécuté en SSH
sur l'hyperviseur. `_check_ssrf` (déjà utilisé par compose_sources/recipe_sources)
doit bloquer une URL qui résout vers une adresse interne, avant tout appel httpx.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from portal.auth.rbac import UserInfo
from portal.config.models import (
    AuthConfig,
    GlobalConfig,
    HostConfig,
    Hypervisor,
    HypervisorType,
    OidcConfig,
    ServerConfig,
)

_METADATA_URL = "http://169.254.169.254/spec"


def _cfg(hyp_type: HypervisorType, node: Hypervisor) -> GlobalConfig:
    return GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hypervisor_types=[hyp_type],
        hypervisors=[node],
    )


@pytest.mark.asyncio
async def test_fetch_spec_for_type_blocks_internal_address() -> None:
    """_fetch_spec_for_type (GET /admin/.../script) rejette une URL vers le lien-local
    169.254.169.254 (endpoint metadata cloud, cible SSRF classique) sans jamais
    appeler httpx."""
    from portal.routes.proxmox import _fetch_spec_for_type

    hyp_type = HypervisorType(name="proxmox", add_script=_METADATA_URL)

    with patch("portal.routes.proxmox.httpx.AsyncClient") as mock_client_cls:
        with pytest.raises(HTTPException) as exc_info:
            await _fetch_spec_for_type(hyp_type)
        assert exc_info.value.status_code == 422
        assert "blocked internal address" in str(exc_info.value.detail)
        mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_run_destroy_script_blocks_internal_address_no_ssh() -> None:
    """_run_destroy_script (déclenché à la suppression d'un host) doit journaliser
    et abandonner sans jamais atteindre httpx ni _ssh_stream si l'URL est bloquée."""
    from portal.routes.proxmox import _run_destroy_script

    hyp_type = HypervisorType(name="proxmox", destroy_script=_METADATA_URL)
    node = Hypervisor(
        name="pve01", address="10.0.0.5", ssh_key_path="/data/k", hypervisor_type="proxmox"
    )
    cfg = _cfg(hyp_type, node)
    host_cfg = HostConfig(name="vm-01", type="ssh", proxmox_node="pve01", vmid="100")

    with (
        patch("portal.routes.proxmox.httpx.AsyncClient") as mock_client_cls,
        patch("portal.routes.proxmox._ssh_stream", new_callable=AsyncMock) as mock_ssh,
    ):
        await _run_destroy_script(cfg, host_cfg)

    mock_client_cls.assert_not_called()
    mock_ssh.assert_not_called()


@pytest.mark.asyncio
async def test_execute_hypervisor_destroy_script_blocks_internal_address() -> None:
    """POST /admin/hypervisors/{name}/execute-destroy rejette (422) une URL bloquée
    avant tout appel httpx."""
    from portal.routes.proxmox import DestroyRequest, execute_hypervisor_destroy_script

    hyp_type = HypervisorType(name="proxmox", destroy_script=_METADATA_URL)
    node = Hypervisor(
        name="pve01", address="10.0.0.5", ssh_key_path="/data/k", hypervisor_type="proxmox"
    )
    cfg = _cfg(hyp_type, node)
    user = UserInfo(login="admin", roles=["admin"])

    with (
        patch("portal.routes.proxmox.load_global", return_value=cfg),
        patch("portal.routes.proxmox.httpx.AsyncClient") as mock_client_cls,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await execute_hypervisor_destroy_script(
                name="pve01", body=DestroyRequest(vmid="100"), user=user
            )
        assert exc_info.value.status_code == 422
        assert "blocked internal address" in str(exc_info.value.detail)
        mock_client_cls.assert_not_called()
