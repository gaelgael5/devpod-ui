from __future__ import annotations

import os
from pathlib import Path

import bcrypt as _bcrypt
import pytest
from fastapi.testclient import TestClient


def _hash(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _make_app(tmp_path: Path, *, oidc_issuer: str = "", oidc_client_id: str = "",
              local_user: str = "", local_password_hash: str = "") -> TestClient:
    import portal.settings as mod

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    os.environ["OIDC_ISSUER"] = oidc_issuer
    os.environ["OIDC_CLIENT_ID"] = oidc_client_id
    os.environ["LOCAL_USER"] = local_user
    os.environ["LOCAL_PASSWORD_HASH"] = local_password_hash
    mod._settings = None

    from portal.app import create_app

    app = create_app()
    return TestClient(app)


def _cleanup() -> None:
    import portal.settings as mod

    for key in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "LOCAL_USER", "LOCAL_PASSWORD_HASH"):
        os.environ.pop(key, None)
    mod._settings = None


# ── GET /auth/config ────────────────────────────────────────────────────────


def test_auth_config_all_disabled(tmp_path: Path) -> None:
    try:
        client = _make_app(tmp_path)
        resp = client.get("/auth/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["oidc_enabled"] is False
        assert data["local_auth_enabled"] is False
    finally:
        _cleanup()


def test_auth_config_oidc_enabled(tmp_path: Path) -> None:
    try:
        client = _make_app(tmp_path, oidc_issuer="https://kc/realms/r", oidc_client_id="app")
        resp = client.get("/auth/config")
        assert resp.status_code == 200
        assert resp.json()["oidc_enabled"] is True
        assert resp.json()["local_auth_enabled"] is False
    finally:
        _cleanup()


def test_auth_config_local_enabled(tmp_path: Path) -> None:
    h = _hash("secret")
    try:
        client = _make_app(tmp_path, local_user="admin", local_password_hash=h)
        resp = client.get("/auth/config")
        assert resp.status_code == 200
        assert resp.json()["oidc_enabled"] is False
        assert resp.json()["local_auth_enabled"] is True
    finally:
        _cleanup()


# ── POST /auth/local-login ───────────────────────────────────────────────────


def test_local_login_not_configured(tmp_path: Path) -> None:
    try:
        client = _make_app(tmp_path)
        resp = client.post("/auth/local-login", json={"username": "admin", "password": "x"})
        assert resp.status_code == 404
    finally:
        _cleanup()


def test_local_login_wrong_password(tmp_path: Path) -> None:
    h = _hash("correct")
    try:
        client = _make_app(tmp_path, local_user="admin", local_password_hash=h)
        resp = client.post("/auth/local-login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401
    finally:
        _cleanup()


def test_local_login_wrong_username(tmp_path: Path) -> None:
    h = _hash("correct")
    try:
        client = _make_app(tmp_path, local_user="admin", local_password_hash=h)
        resp = client.post("/auth/local-login", json={"username": "other", "password": "correct"})
        assert resp.status_code == 401
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_local_login_success(tmp_path: Path) -> None:
    h = _hash("s3cr3t")
    try:
        client = _make_app(tmp_path, local_user="admin", local_password_hash=h)
        resp = client.post("/auth/local-login", json={"username": "admin", "password": "s3cr3t"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        # session cookie présent
        assert "portal_session" in client.cookies
    finally:
        _cleanup()
