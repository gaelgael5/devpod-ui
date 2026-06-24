# backend/tests/test_hypervisor_test_params.py
"""Lot B — paramétrage host de test par type d'hyperviseur."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


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


# ── modèle ────────────────────────────────────────────────────────────────────


def test_hypervisor_type_test_host_params_default() -> None:
    from portal.config.models import HypervisorType

    assert HypervisorType(name="proxmox-clone").test_host_params == {}


def test_hypervisor_type_test_host_params_set() -> None:
    from portal.config.models import HypervisorType

    ht = HypervisorType(name="proxmox-clone", test_host_params={"MEMORY": "2048"})
    assert ht.test_host_params["MEMORY"] == "2048"


# ── PUT /hypervisor-types/{name}/test-params ─────────────────────────────────


@pytest.mark.asyncio
async def test_set_test_host_params_saves() -> None:
    from portal.config.models import HypervisorType
    from portal.routes.proxmox import TestHostParamsRequest, set_test_host_params

    cfg = _cfg([HypervisorType(name="proxmox-clone", add_script="http://x")])
    with (
        patch("portal.routes.proxmox.load_global", return_value=cfg),
        patch("portal.routes.proxmox.save_global", new_callable=AsyncMock) as save,
    ):
        result = await set_test_host_params(
            "proxmox-clone",
            TestHostParamsRequest(params={"MEMORY": "2048", "STORAGE": "auto"}),
            user=_admin(),
        )
    assert result["test_host_params"] == {"MEMORY": "2048", "STORAGE": "auto"}
    save.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_test_host_params_unknown_type_404() -> None:
    from portal.routes.proxmox import TestHostParamsRequest, set_test_host_params

    cfg = _cfg([])
    with (
        patch("portal.routes.proxmox.load_global", return_value=cfg),
        patch("portal.routes.proxmox.save_global", new_callable=AsyncMock),
        pytest.raises(HTTPException) as ei,
    ):
        await set_test_host_params("nope", TestHostParamsRequest(params={}), user=_admin())
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_update_hypervisor_type_preserves_test_params() -> None:
    from portal.config.models import HypervisorType
    from portal.routes.proxmox import HypervisorTypeRequest, update_hypervisor_type

    cfg = _cfg(
        [
            HypervisorType(
                name="proxmox-clone",
                add_script="http://old",
                test_host_params={"MEMORY": "4096"},
            )
        ]
    )
    with (
        patch("portal.routes.proxmox.load_global", return_value=cfg),
        patch("portal.routes.proxmox.save_global", new_callable=AsyncMock),
    ):
        result = await update_hypervisor_type(
            "proxmox-clone",
            HypervisorTypeRequest(name="proxmox-clone", add_script="http://new"),
            user=_admin(),
        )
    assert result["test_host_params"] == {"MEMORY": "4096"}  # préservé
    assert result["add_script"] == "http://new"
