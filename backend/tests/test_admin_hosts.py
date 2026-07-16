"""Tests Task 3 — routes admin hosts : CRUD hosts + bootstrap-ssh.

Approche : tests unitaires avec mocks AsyncMock pour éviter la dépendance
à un container PostgreSQL dans la CI sans fixture docker.
Les scénarios couverts :
  - add_host stocke ci_password dans harpo et retourne un slug (pas le mot de passe)
  - add_host sans ci_password retourne ci_password_secret_slug vide
  - update_host met à jour le secret harpo si nouveau ci_password fourni
  - update_host conserve l'ancien slug si ci_password non fourni
  - delete_host appelle delete_system_secret + delete_system_cert si slugs présents
  - bootstrap_ssh génère ed25519, stocke dans harpo_certificates, ne crée pas de fichier
  - get_host_cert retourne public_key depuis harpo pour host ssh
  - HostCreateRequest rejette les champs inconnus (extra=forbid)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError


def _req(session_id: str = "sid-1") -> MagicMock:
    """Request factice portant une session (vault) pour add/update host."""
    request = MagicMock()
    request.session = {"session_id": session_id}
    return request


# ─── HostCreateRequest ────────────────────────────────────────────────────────


def test_host_create_request_forbids_extra() -> None:
    """HostCreateRequest doit rejeter les champs inconnus."""
    from portal.routes.admin import HostCreateRequest

    with pytest.raises(ValidationError):
        HostCreateRequest(
            name="test",
            type="ssh",
            unknown_field="oops",
        )


def test_host_create_request_minimal_ssh() -> None:
    """HostCreateRequest accepte les champs minimaux pour un host SSH."""
    from portal.routes.admin import HostCreateRequest

    req = HostCreateRequest(name="my-host", type="ssh")
    assert req.name == "my-host"
    assert req.type == "ssh"
    assert req.ci_password == ""


def test_host_create_request_docker_cert_slug_invalid() -> None:
    """docker_cert_slug doit respecter le format slug du gestionnaire de certificats."""
    from portal.routes.admin import HostCreateRequest

    with pytest.raises(ValidationError):
        HostCreateRequest(
            name="node1",
            type="docker-tls",
            docker_cert_slug="../etc/passwd",
        )


def test_host_create_request_docker_cert_slug_valid() -> None:
    from portal.routes.admin import HostCreateRequest

    req = HostCreateRequest(name="node1", type="docker-tls", docker_cert_slug="docker-node1")
    assert req.docker_cert_slug == "docker-node1"


def test_host_create_request_ssh_cert_slug_invalid() -> None:
    from portal.routes.admin import HostCreateRequest

    with pytest.raises(ValidationError):
        HostCreateRequest(name="vm-01", type="ssh", ssh_cert_slug="../etc/passwd")


def test_host_create_request_ssh_cert_slug_valid() -> None:
    from portal.routes.admin import HostCreateRequest

    req = HostCreateRequest(name="vm-01", type="ssh", ssh_cert_slug="my-key")
    assert req.ssh_cert_slug == "my-key"


def test_host_create_request_accepts_usage_autres() -> None:
    """La catégorie « autres » (inventaire simple) est un usage valide."""
    from portal.config.models import HostConfig
    from portal.routes.admin import HostCreateRequest

    req = HostCreateRequest(name="backup-srv", type="ssh", usage="autres")
    assert req.usage == "autres"
    host = HostConfig(name="backup-srv", type="ssh", usage="autres")
    assert host.usage == "autres"


def test_host_create_request_with_ci_password() -> None:
    from portal.routes.admin import HostCreateRequest

    req = HostCreateRequest(
        name="vm-01",
        type="ssh",
        address="debian@192.168.1.10",
        ci_password="S3cr3t!",
        proxmox_node="pve",
        vmid="200",
    )
    assert req.ci_password == "S3cr3t!"
    assert req.address == "debian@192.168.1.10"


# ─── add_host ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_host_stores_ci_password_slug() -> None:
    """add_host avec ci_password doit appeler store_system_secret et retourner le slug."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, OidcConfig, ServerConfig
    from portal.routes.admin import HostCreateRequest, add_host

    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = HostCreateRequest(
        name="test-vm-01",
        type="ssh",
        address="debian@192.168.1.10",
        proxmox_node="pve",
        vmid="200",
        ci_password="SuperSecret123!",
    )

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.store_system_secret", new_callable=AsyncMock) as mock_store,
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock) as mock_save,
    ):
        result = await add_host(request=_req(), body=body, user=user, conn=conn)

    # Le slug est présent, le mot de passe brut n'est PAS dans la réponse
    assert result["ci_password_secret_slug"] == "host.test-vm-01.ci-password"
    assert "ci_password" not in result
    assert "key_path" not in result

    # store_system_secret a été appelé une fois avec le bon slug
    mock_store.assert_called_once()
    call_kwargs = mock_store.call_args.kwargs
    assert call_kwargs["slug"] == "host.test-vm-01.ci-password"
    assert call_kwargs["value"] == "SuperSecret123!"
    assert call_kwargs["storage_type"] == "local"  # toujours forcé local par le backend

    # save_global_db a été appelé avec la conn partagée
    mock_save.assert_called_once()
    save_args = mock_save.call_args
    assert save_args.args[1] is conn or save_args.kwargs.get("conn") is conn


@pytest.mark.asyncio
async def test_add_host_without_ci_password() -> None:
    """add_host sans ci_password laisse ci_password_secret_slug vide."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, OidcConfig, ServerConfig
    from portal.routes.admin import HostCreateRequest, add_host

    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = HostCreateRequest(
        name="manual-ssh-host",
        type="ssh",
        address="debian@10.0.0.5",
    )

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.store_system_secret", new_callable=AsyncMock) as mock_store,
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
    ):
        result = await add_host(request=_req(), body=body, user=user, conn=conn)

    assert result["ci_password_secret_slug"] == ""
    assert result["host_cert_slug"] == ""
    # store_system_secret ne doit pas être appelé sans ci_password
    mock_store.assert_not_called()


@pytest.mark.asyncio
async def test_add_host_conflict_409() -> None:
    """add_host sur un nom déjà existant doit retourner 409."""
    from fastapi import HTTPException

    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, HostConfig, OidcConfig, ServerConfig
    from portal.routes.admin import HostCreateRequest, add_host

    existing = HostConfig(name="existing-host", type="ssh")
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[existing],
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = HostCreateRequest(name="existing-host", type="docker-tls")

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        pytest.raises(HTTPException) as exc_info,
    ):
        await add_host(request=_req(), body=body, user=user, conn=conn)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_add_host_stores_docker_cert_slug() -> None:
    """add_host avec docker_cert_slug enregistre la référence sur le host."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, OidcConfig, ServerConfig
    from portal.routes.admin import HostCreateRequest, add_host

    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = HostCreateRequest(
        name="node1",
        type="docker-tls",
        docker_host="tcp://192.168.1.50:2376",
        docker_cert_slug="docker-node1",
    )

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
        patch("portal.routes.admin._materialize_docker_cert", new_callable=AsyncMock) as mock_mat,
    ):
        result = await add_host(request=_req("sid-42"), body=body, user=user, conn=conn)

    assert result["docker_cert_slug"] == "docker-node1"
    # Le bundle est matérialisé à l'association, avec la session admin.
    mock_mat.assert_awaited_once_with("admin", "sid-42", "node1", "docker-node1", conn)


# ─── _materialize_docker_cert ────────────────────────────────────────────────


def _cert_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "slug": "docker-node1",
        "label": "Docker node1",
        "cert_type": "tls-rsa-4096",
        "public_key": "-----BEGIN CERTIFICATE-----\nCLIENT\n-----END CERTIFICATE-----\n",
        "ca_pem": "-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----\n",
        "owner_login": "admin",
        "is_own": True,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_materialize_docker_cert_writes_bundle() -> None:
    """Cas nominal : cert tls-* importé avec CA → bundle matérialisé."""
    from portal.routes.admin import _materialize_docker_cert

    conn = AsyncMock()
    with (
        patch("portal.routes.admin.get_certificate", new_callable=AsyncMock) as mock_get,
        patch("portal.routes.admin.reveal_private_key", new_callable=AsyncMock) as mock_reveal,
        patch("portal.routes.admin.materialize_host_bundle", new_callable=AsyncMock) as mock_bundle,
    ):
        mock_get.return_value = _cert_row()
        mock_reveal.return_value = "-----BEGIN PRIVATE KEY-----\nK\n-----END PRIVATE KEY-----\n"
        await _materialize_docker_cert("admin", "sid-1", "node1", "docker-node1", conn)

    mock_reveal.assert_awaited_once_with("admin", "sid-1", "docker-node1", conn)
    mock_bundle.assert_awaited_once_with(
        "node1",
        ca_pem=_cert_row()["ca_pem"],
        cert_pem=_cert_row()["public_key"],
        key_pem="-----BEGIN PRIVATE KEY-----\nK\n-----END PRIVATE KEY-----\n",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "status"),
    [
        (None, 404),  # cert introuvable
        (_cert_row(cert_type="ssh-ed25519"), 422),  # pas un cert TLS
        (_cert_row(is_own=False, owner_login="bob"), 422),  # cert public d'un autre user
        (_cert_row(public_key="ssh-rsa AAAA"), 422),  # entrée générée = pas un X.509
        (_cert_row(ca_pem=None), 422),  # CA manquant
    ],
)
async def test_materialize_docker_cert_rejects_unusable_cert(
    row: dict[str, object] | None, status: int
) -> None:
    from fastapi import HTTPException

    from portal.routes.admin import _materialize_docker_cert

    conn = AsyncMock()
    with (
        patch("portal.routes.admin.get_certificate", new_callable=AsyncMock) as mock_get,
        patch("portal.routes.admin.materialize_host_bundle", new_callable=AsyncMock) as mock_bundle,
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_get.return_value = row
        await _materialize_docker_cert("admin", "sid-1", "node1", "docker-node1", conn)

    assert exc_info.value.status_code == status
    mock_bundle.assert_not_called()


@pytest.mark.asyncio
async def test_materialize_docker_cert_vault_locked_403() -> None:
    """Vault verrouillé au reveal → 403 vault_locked (pas de bundle écrit)."""
    from fastapi import HTTPException

    from portal.certificates.service import VaultLocked
    from portal.routes.admin import _materialize_docker_cert

    conn = AsyncMock()
    with (
        patch("portal.routes.admin.get_certificate", new_callable=AsyncMock) as mock_get,
        patch("portal.routes.admin.reveal_private_key", new_callable=AsyncMock) as mock_reveal,
        patch("portal.routes.admin.materialize_host_bundle", new_callable=AsyncMock) as mock_bundle,
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_get.return_value = _cert_row()
        mock_reveal.side_effect = VaultLocked("locked")
        await _materialize_docker_cert("admin", "sid-1", "node1", "docker-node1", conn)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "vault_locked"
    mock_bundle.assert_not_called()


# ─── _materialize_ssh_cert ───────────────────────────────────────────────────


def _ssh_cert_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "slug": "my-key",
        "label": "Ma clé",
        "cert_type": "ssh-ed25519",
        "public_key": "ssh-ed25519 AAAAC3Nz... user@host",
        "ca_pem": None,
        "owner_login": "admin",
        "is_own": True,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_materialize_ssh_cert_stores_system_cert() -> None:
    """Cas nominal : cert ssh-* du gestionnaire → cert système host.<name>.cert."""
    from portal.routes.admin import _materialize_ssh_cert

    conn = AsyncMock()
    with (
        patch("portal.routes.admin.get_certificate", new_callable=AsyncMock) as mock_get,
        patch("portal.routes.admin.reveal_private_key", new_callable=AsyncMock) as mock_reveal,
        patch("portal.routes.admin.store_system_cert", new_callable=AsyncMock) as mock_store,
    ):
        mock_get.return_value = _ssh_cert_row()
        mock_reveal.return_value = "-----BEGIN OPENSSH PRIVATE KEY-----\nK\n-----END..."
        slug = await _materialize_ssh_cert("admin", "sid-9", "vm-01", "my-key", conn)

    assert slug == "host.vm-01.cert"
    mock_reveal.assert_awaited_once_with("admin", "sid-9", "my-key", conn)
    mock_store.assert_awaited_once()
    kw = mock_store.call_args.kwargs
    assert kw["slug"] == "host.vm-01.cert"
    assert kw["cert_type"] == "ssh-ed25519"
    assert kw["public_key"] == "ssh-ed25519 AAAAC3Nz... user@host"
    assert kw["private_pem"] == "-----BEGIN OPENSSH PRIVATE KEY-----\nK\n-----END..."
    assert kw["storage_type"] == "local"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "status"),
    [
        (None, 404),  # introuvable
        (_ssh_cert_row(cert_type="tls-rsa-4096"), 422),  # pas un cert SSH
        (_ssh_cert_row(is_own=False, owner_login="bob"), 422),  # cert d'un autre user
    ],
)
async def test_materialize_ssh_cert_rejects_unusable(
    row: dict[str, object] | None, status: int
) -> None:
    from fastapi import HTTPException

    from portal.routes.admin import _materialize_ssh_cert

    conn = AsyncMock()
    with (
        patch("portal.routes.admin.get_certificate", new_callable=AsyncMock) as mock_get,
        patch("portal.routes.admin.store_system_cert", new_callable=AsyncMock) as mock_store,
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_get.return_value = row
        await _materialize_ssh_cert("admin", "sid-1", "vm-01", "my-key", conn)

    assert exc_info.value.status_code == status
    mock_store.assert_not_called()


@pytest.mark.asyncio
async def test_materialize_ssh_cert_vault_locked_403() -> None:
    from fastapi import HTTPException

    from portal.certificates.service import VaultLocked
    from portal.routes.admin import _materialize_ssh_cert

    conn = AsyncMock()
    with (
        patch("portal.routes.admin.get_certificate", new_callable=AsyncMock) as mock_get,
        patch("portal.routes.admin.reveal_private_key", new_callable=AsyncMock) as mock_reveal,
        patch("portal.routes.admin.store_system_cert", new_callable=AsyncMock) as mock_store,
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_get.return_value = _ssh_cert_row()
        mock_reveal.side_effect = VaultLocked("locked")
        await _materialize_ssh_cert("admin", "sid-1", "vm-01", "my-key", conn)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "vault_locked"
    mock_store.assert_not_called()


@pytest.mark.asyncio
async def test_add_ssh_host_with_cert_sets_host_cert_slug() -> None:
    """add_host ssh avec ssh_cert_slug matérialise le cert et pose host_cert_slug."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, OidcConfig, ServerConfig
    from portal.routes.admin import HostCreateRequest, add_host

    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
    )
    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = HostCreateRequest(
        name="vm-01", type="ssh", address="debian@10.0.0.5", ssh_cert_slug="my-key"
    )

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
        patch("portal.routes.admin._materialize_ssh_cert", new_callable=AsyncMock) as mock_mat,
    ):
        mock_mat.return_value = "host.vm-01.cert"
        result = await add_host(request=_req("sid-7"), body=body, user=user, conn=conn)

    mock_mat.assert_awaited_once_with("admin", "sid-7", "vm-01", "my-key", conn)
    assert result["host_cert_slug"] == "host.vm-01.cert"


@pytest.mark.asyncio
async def test_update_ssh_host_with_cert_rematerializes() -> None:
    """update_host ssh avec ssh_cert_slug rematérialise et remplace host_cert_slug."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, HostConfig, OidcConfig, ServerConfig
    from portal.routes.admin import HostCreateRequest, update_host

    existing = HostConfig(name="vm-01", type="ssh", host_cert_slug="host.vm-01.cert")
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[existing],
    )
    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = HostCreateRequest(
        name="vm-01", type="ssh", address="debian@10.0.0.5", ssh_cert_slug="other-key"
    )

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
        patch("portal.routes.admin._materialize_ssh_cert", new_callable=AsyncMock) as mock_mat,
    ):
        mock_mat.return_value = "host.vm-01.cert"
        result = await update_host(request=_req(), name="vm-01", body=body, user=user, conn=conn)

    mock_mat.assert_awaited_once()
    assert result["host_cert_slug"] == "host.vm-01.cert"


@pytest.mark.asyncio
async def test_update_ssh_host_without_cert_preserves_bootstrap_slug() -> None:
    """update_host ssh sans ssh_cert_slug ne touche pas host_cert_slug (bootstrap conservé)."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, HostConfig, OidcConfig, ServerConfig
    from portal.routes.admin import HostCreateRequest, update_host

    existing = HostConfig(name="vm-01", type="ssh", host_cert_slug="host.vm-01.cert")
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[existing],
    )
    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = HostCreateRequest(name="vm-01", type="ssh", address="debian@10.0.0.5")

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
        patch("portal.routes.admin._materialize_ssh_cert", new_callable=AsyncMock) as mock_mat,
    ):
        result = await update_host(request=_req(), name="vm-01", body=body, user=user, conn=conn)

    mock_mat.assert_not_called()
    assert result["host_cert_slug"] == "host.vm-01.cert"


# ─── update_host ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_host_stores_new_ci_password() -> None:
    """update_host avec ci_password appelle store_system_secret."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, HostConfig, OidcConfig, ServerConfig
    from portal.routes.admin import HostCreateRequest, update_host

    existing = HostConfig(
        name="vm-01", type="ssh", ci_password_secret_slug="host.vm-01.ci-password"
    )
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[existing],
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = HostCreateRequest(
        name="vm-01",
        type="ssh",
        ci_password="NewPass!",
    )

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.store_system_secret", new_callable=AsyncMock) as mock_store,
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
    ):
        result = await update_host(request=_req(), name="vm-01", body=body, user=user, conn=conn)

    mock_store.assert_called_once()
    assert result["ci_password_secret_slug"] == "host.vm-01.ci-password"


@pytest.mark.asyncio
async def test_update_host_preserves_slug_without_ci_password() -> None:
    """update_host sans ci_password conserve le slug existant, n'appelle pas store."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, HostConfig, OidcConfig, ServerConfig
    from portal.routes.admin import HostCreateRequest, update_host

    existing = HostConfig(
        name="vm-01",
        type="ssh",
        ci_password_secret_slug="host.vm-01.ci-password",
        host_cert_slug="host.vm-01.cert",
    )
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[existing],
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = HostCreateRequest(
        name="vm-01",
        type="ssh",
        address="debian@10.0.0.1",
        # pas de ci_password
    )

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.store_system_secret", new_callable=AsyncMock) as mock_store,
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
    ):
        result = await update_host(request=_req(), name="vm-01", body=body, user=user, conn=conn)

    mock_store.assert_not_called()
    assert result["ci_password_secret_slug"] == "host.vm-01.ci-password"
    assert result["host_cert_slug"] == "host.vm-01.cert"


@pytest.mark.asyncio
async def test_update_host_docker_cert_slug_set_and_clear() -> None:
    """update_host prend docker_cert_slug du body ('' = dissocier, None = préservé)."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, HostConfig, OidcConfig, ServerConfig
    from portal.routes.admin import HostCreateRequest, update_host

    existing = HostConfig(
        name="node1",
        type="docker-tls",
        docker_host="tcp://192.168.1.50:2376",
        docker_cert_slug="old-cert",
    )
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[existing],
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
        patch("portal.routes.admin._materialize_docker_cert", new_callable=AsyncMock) as mock_mat,
        patch("portal.routes.admin.remove_host_bundle", new_callable=AsyncMock) as mock_rm,
    ):
        # Nouveau slug → remplacé, bundle rematérialisé
        body = HostCreateRequest(
            name="node1",
            type="docker-tls",
            docker_host="tcp://192.168.1.50:2376",
            docker_cert_slug="new-cert",
        )
        result = await update_host(request=_req(), name="node1", body=body, user=user, conn=conn)
        assert result["docker_cert_slug"] == "new-cert"
        mock_mat.assert_awaited_once_with("admin", "sid-1", "node1", "new-cert", conn)
        mock_rm.assert_not_called()

        # "" explicite → dissocié, bundle supprimé
        mock_mat.reset_mock()
        body = HostCreateRequest(
            name="node1",
            type="docker-tls",
            docker_host="tcp://192.168.1.50:2376",
            docker_cert_slug="",
        )
        result = await update_host(request=_req(), name="node1", body=body, user=user, conn=conn)
        assert result["docker_cert_slug"] == ""
        mock_mat.assert_not_called()
        mock_rm.assert_awaited_once_with("node1")


@pytest.mark.asyncio
async def test_update_host_docker_cert_slug_preserved_when_absent() -> None:
    """update_host sans docker_cert_slug (None) conserve la valeur existante."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, HostConfig, OidcConfig, ServerConfig
    from portal.routes.admin import HostCreateRequest, update_host

    existing = HostConfig(
        name="node1",
        type="docker-tls",
        docker_host="tcp://192.168.1.50:2376",
        docker_cert_slug="kept-cert",
    )
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[existing],
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = HostCreateRequest(
        name="node1",
        type="docker-tls",
        docker_host="tcp://192.168.1.50:2376",
    )

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
        patch("portal.routes.admin._materialize_docker_cert", new_callable=AsyncMock) as mock_mat,
        patch("portal.routes.admin.remove_host_bundle", new_callable=AsyncMock) as mock_rm,
    ):
        result = await update_host(request=_req(), name="node1", body=body, user=user, conn=conn)

    assert result["docker_cert_slug"] == "kept-cert"
    # Slug inchangé : ni rematérialisation (exigerait le vault déverrouillé), ni purge.
    mock_mat.assert_not_called()
    mock_rm.assert_not_called()


@pytest.mark.asyncio
async def test_update_host_name_mismatch_422() -> None:
    """update_host avec name mismatch body/URL doit retourner 422."""
    from fastapi import HTTPException

    from portal.auth.rbac import UserInfo
    from portal.routes.admin import HostCreateRequest, update_host

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = HostCreateRequest(name="other-name", type="ssh")

    with pytest.raises(HTTPException) as exc_info:
        await update_host(request=_req(), name="vm-01", body=body, user=user, conn=conn)

    assert exc_info.value.status_code == 422


# ─── delete_host ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_host_cleans_up_harpo() -> None:
    """delete_host appelle delete_system_secret et delete_system_cert si slugs présents."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, HostConfig, OidcConfig, ServerConfig
    from portal.routes.admin import delete_host

    existing = HostConfig(
        name="vm-01",
        type="ssh",
        ci_password_secret_slug="host.vm-01.ci-password",
        host_cert_slug="host.vm-01.cert",
    )
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[existing],
    )

    conn = AsyncMock()
    # Simuler qu'il n'y a pas de workspaces sur ce host
    rows_result = MagicMock()
    rows_result.mappings.return_value.all.return_value = []
    conn.execute.return_value = rows_result
    user = UserInfo(login="admin", roles=["admin"])

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.delete_system_secret", new_callable=AsyncMock) as mock_del_sec,
        patch("portal.routes.admin.delete_system_cert", new_callable=AsyncMock) as mock_del_cert,
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
        patch("portal.routes.proxmox._run_destroy_script", new_callable=AsyncMock),
    ):
        await delete_host(name="vm-01", user=user, conn=conn)

    mock_del_sec.assert_called_once_with("host.vm-01.ci-password", conn)
    mock_del_cert.assert_called_once_with("host.vm-01.cert", conn)


@pytest.mark.asyncio
async def test_delete_host_no_slugs_no_harpo_calls() -> None:
    """delete_host sans slugs ne doit pas appeler les fonctions harpo."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, HostConfig, OidcConfig, ServerConfig
    from portal.routes.admin import delete_host

    existing = HostConfig(name="vm-01", type="ssh")
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[existing],
    )

    conn = AsyncMock()
    rows_result = MagicMock()
    rows_result.mappings.return_value.all.return_value = []
    conn.execute.return_value = rows_result
    user = UserInfo(login="admin", roles=["admin"])

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.delete_system_secret", new_callable=AsyncMock) as mock_del_sec,
        patch("portal.routes.admin.delete_system_cert", new_callable=AsyncMock) as mock_del_cert,
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
        patch("portal.routes.proxmox._run_destroy_script", new_callable=AsyncMock),
    ):
        await delete_host(name="vm-01", user=user, conn=conn)

    mock_del_sec.assert_not_called()
    mock_del_cert.assert_not_called()


@pytest.mark.asyncio
async def test_delete_host_removes_docker_bundle() -> None:
    """delete_host purge le bundle mTLS par host si docker_cert_slug présent."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import AuthConfig, GlobalConfig, HostConfig, OidcConfig, ServerConfig
    from portal.routes.admin import delete_host

    existing = HostConfig(
        name="node1",
        type="docker-tls",
        docker_host="tcp://192.168.1.50:2376",
        docker_cert_slug="docker-node1",
    )
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[existing],
    )

    conn = AsyncMock()
    rows_result = MagicMock()
    rows_result.mappings.return_value.all.return_value = []
    conn.execute.return_value = rows_result
    user = UserInfo(login="admin", roles=["admin"])

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock),
        patch("portal.routes.proxmox._run_destroy_script", new_callable=AsyncMock),
        patch("portal.routes.admin.remove_host_bundle", new_callable=AsyncMock) as mock_rm,
    ):
        await delete_host(name="node1", user=user, conn=conn)

    mock_rm.assert_awaited_once_with("node1")


# ─── bootstrap-ssh ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_ssh_generates_key_and_stores_in_harpo() -> None:
    """bootstrap_host_ssh génère ed25519 et stocke dans harpo, retourne public_key."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import (
        AuthConfig,
        GlobalConfig,
        HostConfig,
        Hypervisor,
        OidcConfig,
        ServerConfig,
    )
    from portal.routes.admin import BootstrapSshRequest, bootstrap_host_ssh

    hyp = Hypervisor(
        name="pve",
        address="192.168.1.1",
        ssh_user="root",
        ssh_port=22,
        ssh_key_path="/data/keys/pve",
        pve_node="pve",
    )
    host = HostConfig(name="vm-01", type="ssh", proxmox_node="pve")
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[host],
        hypervisors=[hyp],
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = BootstrapSshRequest(address="debian@192.168.1.10", proxmox_node="pve")

    # Mock SSH pivot : retourne code 0
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"", b"")

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        patch("portal.routes.admin.store_system_cert", new_callable=AsyncMock) as mock_store,
        patch("portal.routes.admin.save_global_db", new_callable=AsyncMock) as mock_save,
        patch("portal.routes.admin.asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await bootstrap_host_ssh(name="vm-01", body=body, user=user, conn=conn)

    # Résultat contient public_key
    assert "public_key" in result
    pub = result["public_key"]
    assert pub.startswith("ssh-ed25519 ")

    # store_system_cert appelé avec bon slug et cert_type
    mock_store.assert_called_once()
    kw = mock_store.call_args.kwargs
    assert kw["slug"] == "host.vm-01.cert"
    assert kw["cert_type"] == "ssh-ed25519"
    assert kw["public_key"] == pub

    # La clé privée ne sort pas de la réponse
    assert "private_pem" not in result
    assert "private_key" not in result

    # save_global_db appelé
    mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_bootstrap_ssh_invalid_address_422() -> None:
    """bootstrap_host_ssh rejette les adresses invalides."""
    from fastapi import HTTPException

    from portal.auth.rbac import UserInfo
    from portal.config.models import (
        AuthConfig,
        GlobalConfig,
        HostConfig,
        OidcConfig,
        ServerConfig,
    )
    from portal.routes.admin import BootstrapSshRequest, bootstrap_host_ssh

    host = HostConfig(name="vm-01", type="ssh", proxmox_node="pve")
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[host],
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = BootstrapSshRequest(address="INVALID-ADDRESS", proxmox_node="pve")

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        pytest.raises(HTTPException) as exc_info,
    ):
        await bootstrap_host_ssh(name="vm-01", body=body, user=user, conn=conn)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_bootstrap_ssh_wrong_host_type_422() -> None:
    """bootstrap_host_ssh rejette les hosts de type docker-tls."""
    from fastapi import HTTPException

    from portal.auth.rbac import UserInfo
    from portal.config.models import (
        AuthConfig,
        GlobalConfig,
        HostConfig,
        OidcConfig,
        ServerConfig,
    )
    from portal.routes.admin import BootstrapSshRequest, bootstrap_host_ssh

    host = HostConfig(name="docker-host", type="docker-tls")
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[host],
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])
    body = BootstrapSshRequest(address="debian@192.168.1.10", proxmox_node="pve")

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        pytest.raises(HTTPException) as exc_info,
    ):
        await bootstrap_host_ssh(name="docker-host", body=body, user=user, conn=conn)

    assert exc_info.value.status_code == 422


# ─── get_host_cert ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_host_cert_ssh_returns_public_key() -> None:
    """get_host_cert pour un host SSH retourne public_key depuis harpo_certificates."""
    from portal.auth.rbac import UserInfo
    from portal.config.models import (
        AuthConfig,
        GlobalConfig,
        HostConfig,
        OidcConfig,
        ServerConfig,
    )
    from portal.routes.admin import get_host_cert

    host = HostConfig(
        name="vm-01",
        type="ssh",
        host_cert_slug="host.vm-01.cert",
    )
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[host],
    )

    conn = AsyncMock()
    # Simuler le retour de la requête harpo_certificates
    row = {"public_key": "ssh-ed25519 AAAAB...", "cert_type": "ssh-ed25519"}
    result_mock = MagicMock()
    result_mock.mappings.return_value.one_or_none.return_value = row
    conn.execute.return_value = result_mock

    user = UserInfo(login="admin", roles=["admin"])

    with patch("portal.routes.admin.load_global", return_value=cfg):
        result = await get_host_cert(name="vm-01", user=user, conn=conn)

    assert result["public_key"] == "ssh-ed25519 AAAAB..."
    assert result["cert_type"] == "ssh-ed25519"


@pytest.mark.asyncio
async def test_get_host_cert_ssh_no_cert_slug_404() -> None:
    """get_host_cert pour un host SSH sans host_cert_slug retourne 404."""
    from fastapi import HTTPException

    from portal.auth.rbac import UserInfo
    from portal.config.models import (
        AuthConfig,
        GlobalConfig,
        HostConfig,
        OidcConfig,
        ServerConfig,
    )
    from portal.routes.admin import get_host_cert

    host = HostConfig(name="vm-01", type="ssh", host_cert_slug="")
    cfg = GlobalConfig(
        version="1",
        server=ServerConfig(base_domain="", external_url=""),
        auth=AuthConfig(oidc=OidcConfig(issuer="", client_id="", client_secret="")),
        hosts=[host],
    )

    conn = AsyncMock()
    user = UserInfo(login="admin", roles=["admin"])

    with (
        patch("portal.routes.admin.load_global", return_value=cfg),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_host_cert(name="vm-01", user=user, conn=conn)

    assert exc_info.value.status_code == 404
