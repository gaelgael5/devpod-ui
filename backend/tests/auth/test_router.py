from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import yaml


@pytest.mark.asyncio
async def test_provision_user_creates_dir_and_config(tmp_path: Path) -> None:
    import portal.settings as mod
    from portal.auth.router import provision_user

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    mod._settings = None

    await provision_user(login="alice", sub="sub-123", data_root=tmp_path)

    user_dir = tmp_path / "users" / "alice"
    assert user_dir.is_dir()
    config_path = user_dir / "config.yaml"
    assert config_path.is_file()

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert uuid.UUID(data["secret_ns"])  # valide


@pytest.mark.asyncio
async def test_provision_user_is_idempotent(tmp_path: Path) -> None:
    import portal.settings as mod
    from portal.auth.router import provision_user

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    mod._settings = None

    await provision_user(login="alice", sub="sub", data_root=tmp_path)
    first_ns = yaml.safe_load(
        (tmp_path / "users" / "alice" / "config.yaml").read_text(encoding="utf-8")
    )["secret_ns"]

    await provision_user(login="alice", sub="sub", data_root=tmp_path)
    second_ns = yaml.safe_load(
        (tmp_path / "users" / "alice" / "config.yaml").read_text(encoding="utf-8")
    )["secret_ns"]

    assert first_ns == second_ns


@pytest.mark.asyncio
async def test_provision_user_rejects_invalid_username(tmp_path: Path) -> None:
    from portal.auth.rbac import UsernameError
    from portal.auth.router import provision_user

    with pytest.raises(UsernameError):
        await provision_user(login="A", sub="sub", data_root=tmp_path)

    assert not (tmp_path / "users" / "A").exists()


def test_login_redirects_to_authorization_endpoint(tmp_path: Path) -> None:
    """GET /auth/login redirige vers l'endpoint OIDC."""
    import httpx
    import respx
    from fastapi.testclient import TestClient

    import portal.auth.router as router_mod
    import portal.settings as mod

    _env_keys = [
        "PORTAL_DATA_ROOT",
        "SESSION_SECRET_KEY",
        "OIDC_ISSUER",
        "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET",
        "OIDC_REDIRECT_URI",
    ]
    _saved = {k: os.environ.get(k) for k in _env_keys}

    try:
        mod._settings = None
        router_mod._oidc_client = None

        os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
        os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
        os.environ["OIDC_ISSUER"] = "https://kc.test/realms/yoops"
        os.environ["OIDC_CLIENT_ID"] = "workspace-portal"
        os.environ["OIDC_CLIENT_SECRET"] = "secret"
        os.environ["OIDC_REDIRECT_URI"] = "https://portal.test/auth/callback"
        mod._settings = None

        from tests.auth.conftest import DISCOVERY_DOC

        with respx.mock:
            respx.get("https://kc.test/realms/yoops/.well-known/openid-configuration").mock(
                return_value=httpx.Response(200, json=DISCOVERY_DOC)
            )
            from portal.app import create_app

            app = create_app()
            with TestClient(app, follow_redirects=False) as client:
                resp = client.get("/auth/login")

        assert resp.status_code in (302, 307)
        location = resp.headers["location"]
        assert "code_challenge=" in location
        assert "code_challenge_method=S256" in location
    finally:
        for k, v in _saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        mod._settings = None
        router_mod._oidc_client = None
