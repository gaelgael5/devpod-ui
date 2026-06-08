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


def test_callback_creates_user_and_session(tmp_path: Path) -> None:
    """GET /auth/callback valide le token, crée le dossier user, stocke la session."""
    import httpx
    import respx

    from tests.auth.conftest import (
        CLIENT_ID,
        DISCOVERY_DOC,
        ISSUER,
        make_id_token,
        make_jwks_response,
    )

    _env_keys = [
        "PORTAL_DATA_ROOT",
        "SESSION_SECRET_KEY",
        "OIDC_ISSUER",
        "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET",
        "OIDC_REDIRECT_URI",
        "DEV_MODE",
    ]
    _saved = {k: os.environ.get(k) for k in _env_keys}

    # Les env vars DOIVENT être positionnées avant tout import de portal.app,
    # car app.py exécute create_app() au niveau module.
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    os.environ["OIDC_ISSUER"] = ISSUER
    os.environ["OIDC_CLIENT_ID"] = CLIENT_ID
    os.environ["OIDC_CLIENT_SECRET"] = "client-secret"
    os.environ["OIDC_REDIRECT_URI"] = "https://portal.test/auth/callback"
    os.environ["DEV_MODE"] = "true"

    try:
        from fastapi.testclient import TestClient

        import portal.auth.router as router_mod
        import portal.settings as mod
        from portal.app import create_app

        mod._settings = None
        router_mod._oidc_client = None

        with respx.mock:
            respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
                return_value=httpx.Response(200, json=DISCOVERY_DOC)
            )
            respx.get(DISCOVERY_DOC["jwks_uri"]).mock(
                return_value=httpx.Response(200, json=make_jwks_response())
            )

            app = create_app()

            with TestClient(app, follow_redirects=False) as client:
                # Étape 1 : login pour obtenir state/nonce/verifier dans la session
                login_resp = client.get("/auth/oidc")
                assert login_resp.status_code in (302, 307)

                # Extraire le state et le nonce depuis la location
                from urllib.parse import parse_qs, urlparse

                location = login_resp.headers["location"]
                parsed = urlparse(location)
                params = parse_qs(parsed.query)
                state = params["state"][0]
                nonce = params["nonce"][0]

                # Générer le token avec le nonce produit par le serveur
                id_token = make_id_token(
                    issuer=ISSUER,
                    client_id=CLIENT_ID,
                    username="alice",
                    roles=["dev"],
                    nonce=nonce,
                )

                # Brancher le mock du token endpoint avec le bon id_token
                respx.post(DISCOVERY_DOC["token_endpoint"]).mock(
                    return_value=httpx.Response(
                        200, json={"id_token": id_token, "access_token": "acc"}
                    )
                )

                # Étape 2 : callback avec le state correct
                # Le TestClient maintient les cookies de session entre les requêtes
                callback_resp = client.get(
                    "/auth/callback",
                    params={"code": "auth-code-123", "state": state},
                )

        assert callback_resp.status_code in (302, 307), (
            f"Expected redirect, got {callback_resp.status_code}: {callback_resp.text}"
        )

        # Vérifier que le dossier user a été créé
        user_dir = tmp_path / "users" / "alice"
        assert user_dir.is_dir(), "User directory should have been created"
        config_path = user_dir / "config.yaml"
        assert config_path.is_file(), "User config.yaml should exist"

        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert uuid.UUID(data["secret_ns"]), "secret_ns should be a valid UUID"

    finally:
        for k, v in _saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import portal.auth.router as router_mod
        import portal.settings as mod

        mod._settings = None
        router_mod._oidc_client = None


def test_caddy_verify_valid_session_returns_200(tmp_path: Path) -> None:
    """GET /auth/caddy/verify — session valide avec rôle dev → 200."""
    from fastapi.testclient import TestClient

    import portal.auth.router as router_mod
    import portal.settings as settings_mod

    _env_keys = ["PORTAL_DATA_ROOT", "SESSION_SECRET_KEY", "DEV_MODE"]
    _saved = {k: os.environ.get(k) for k in _env_keys}
    try:
        os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
        os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
        os.environ["DEV_MODE"] = "true"
        settings_mod._settings = None
        router_mod._oidc_client = None

        from portal.app import create_app

        app = create_app()

        with TestClient(app, raise_server_exceptions=True) as client:
            import portal.auth.rbac as rbac_mod
            from portal.auth.rbac import UserInfo

            def mock_get_current_user(request):  # type: ignore[override]
                return UserInfo(login="alice", roles=["dev"], sub="sub-alice")

            original_fn = rbac_mod.get_current_user
            rbac_mod.get_current_user = mock_get_current_user  # type: ignore[assignment]
            try:
                resp = client.get("/auth/caddy/verify")
                assert resp.status_code == 200
            finally:
                rbac_mod.get_current_user = original_fn

    finally:
        for k, v in _saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings_mod._settings = None
        router_mod._oidc_client = None


def test_caddy_verify_no_session_returns_401(tmp_path: Path) -> None:
    """GET /auth/caddy/verify — pas de session → 401."""
    from fastapi.testclient import TestClient

    import portal.auth.router as router_mod
    import portal.settings as settings_mod

    _env_keys = ["PORTAL_DATA_ROOT", "SESSION_SECRET_KEY", "DEV_MODE"]
    _saved = {k: os.environ.get(k) for k in _env_keys}
    try:
        os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
        os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
        os.environ["DEV_MODE"] = "true"
        settings_mod._settings = None
        router_mod._oidc_client = None

        from portal.app import create_app

        app = create_app()

        with TestClient(app, raise_server_exceptions=True) as client:
            import portal.auth.rbac as rbac_mod

            original_fn = rbac_mod.get_current_user

            def no_session(request) -> None:  # type: ignore[override]
                return None

            rbac_mod.get_current_user = no_session  # type: ignore[assignment]
            try:
                resp = client.get("/auth/caddy/verify")
                assert resp.status_code == 401
            finally:
                rbac_mod.get_current_user = original_fn

    finally:
        for k, v in _saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings_mod._settings = None
        router_mod._oidc_client = None


def test_caddy_verify_wrong_role_returns_401(tmp_path: Path) -> None:
    """GET /auth/caddy/verify — session valide mais rôle inconnu → 401."""
    from fastapi.testclient import TestClient

    import portal.auth.router as router_mod
    import portal.settings as settings_mod

    _env_keys = ["PORTAL_DATA_ROOT", "SESSION_SECRET_KEY", "DEV_MODE"]
    _saved = {k: os.environ.get(k) for k in _env_keys}
    try:
        os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
        os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
        os.environ["DEV_MODE"] = "true"
        settings_mod._settings = None
        router_mod._oidc_client = None

        from portal.app import create_app

        app = create_app()

        with TestClient(app, raise_server_exceptions=True) as client:
            import portal.auth.rbac as rbac_mod
            from portal.auth.rbac import UserInfo

            original_fn = rbac_mod.get_current_user

            def wrong_role(request) -> UserInfo:
                return UserInfo(login="alice", roles=["unknown-role"], sub="sub-alice")

            rbac_mod.get_current_user = wrong_role  # type: ignore[assignment]
            try:
                resp = client.get("/auth/caddy/verify")
                assert resp.status_code == 401
            finally:
                rbac_mod.get_current_user = original_fn

    finally:
        for k, v in _saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings_mod._settings = None
        router_mod._oidc_client = None


def test_login_redirects_to_authorization_endpoint(tmp_path: Path) -> None:
    """GET /auth/oidc redirige vers l'endpoint OIDC."""
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
                resp = client.get("/auth/oidc")

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
