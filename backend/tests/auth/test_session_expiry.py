"""Bug 032 — plafond d'âge absolu de la session (rôles figés dans le cookie).

Le max_age du cookie Starlette est glissant : il ne déconnecte que les sessions
inactives. Ces tests prouvent qu'un plafond ABSOLU depuis `auth_time` expire aussi
les sessions actives, forçant un re-login OIDC qui rafraîchit les rôles Keycloak.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


def _make_request(session: dict) -> MagicMock:
    req = MagicMock()
    req.session = session
    return req


# ── Plafond absolu : get_current_user ────────────────────────────────────────


def test_stale_auth_time_expires_session() -> None:
    """auth_time plus vieux que session_max_age → session traitée comme absente."""
    from portal.auth.rbac import get_current_user
    from portal.settings import get_settings

    max_age = get_settings().session_absolute_max_age
    stale = int(time.time()) - max_age - 1
    req = _make_request({"user": {"login": "bob", "roles": ["admin"]}, "auth_time": stale})
    assert get_current_user(req) is None


def test_fresh_auth_time_keeps_session() -> None:
    from portal.auth.rbac import UserInfo, get_current_user

    req = _make_request(
        {"user": {"login": "bob", "roles": ["admin"]}, "auth_time": int(time.time())}
    )
    user = get_current_user(req)
    assert isinstance(user, UserInfo)
    assert user.login == "bob"


def test_missing_auth_time_is_fail_closed() -> None:
    """Cookie legacy d'avant le fix (pas d'auth_time) → expiré (fail-closed)."""
    from portal.auth.rbac import get_current_user

    req = _make_request({"user": {"login": "bob", "roles": ["admin"]}})
    assert get_current_user(req) is None


# ── Le rôle admin figé ne passe plus require_admin après expiration ──────────


@pytest.mark.asyncio
async def test_require_admin_rejects_stale_admin_session() -> None:
    """Un admin dé-privilégié côté Keycloak ne passe plus require_admin à l'expiration."""
    from portal.auth.rbac import require_admin
    from portal.settings import get_settings

    stale = int(time.time()) - get_settings().session_absolute_max_age - 1
    req = _make_request({"user": {"login": "bob", "roles": ["admin"]}, "auth_time": stale})
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_user_rejects_stale_session() -> None:
    from portal.auth.rbac import require_user
    from portal.settings import get_settings

    stale = int(time.time()) - get_settings().session_absolute_max_age - 1
    req = _make_request({"user": {"login": "alice", "roles": ["dev"]}, "auth_time": stale})
    with pytest.raises(HTTPException) as exc_info:
        await require_user(req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_admin_accepts_fresh_admin_session() -> None:
    from portal.auth.rbac import UserInfo, require_admin

    req = _make_request(
        {"user": {"login": "bob", "roles": ["admin"]}, "auth_time": int(time.time())}
    )
    user = await require_admin(req)
    assert isinstance(user, UserInfo)


# ── Chemin API key : indépendant de auth_time (pas une session) ──────────────


@pytest.mark.asyncio
async def test_api_key_path_ignores_auth_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le Bearer portal_api_key est accepté sans auth_time (ce n'est pas une session)."""
    import portal.auth.rbac as rbac_mod
    from portal.auth.rbac import UserInfo, require_admin_or_api_key

    monkeypatch.setattr(
        rbac_mod,
        "get_settings",
        lambda: type("S", (), {"portal_api_key": "secret-key", "oidc_admin_role": "admin"})(),
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret-key")
    # Session vide (aucun auth_time) : le chemin API key ne doit pas s'en soucier.
    user = await require_admin_or_api_key(_make_request({}), creds)
    assert isinstance(user, UserInfo)
    assert user.login == "__api__"
    assert "admin" in user.roles


# ── Le plafond couvre aussi les proxies qui lisent la session hors dep RBAC ──


def test_session_within_max_age_helper() -> None:
    """Le helper partagé : fail-closed sans auth_time, borné par session_absolute_max_age."""
    from portal.auth.rbac import session_within_max_age
    from portal.settings import get_settings

    max_age = get_settings().session_absolute_max_age
    assert session_within_max_age({"auth_time": int(time.time())}) is True
    assert session_within_max_age({"auth_time": int(time.time()) - max_age - 1}) is False
    assert session_within_max_age({}) is False  # legacy / absent → expiré


def test_active_session_past_idle_window_still_valid() -> None:
    """Le plafond absolu est DÉCOUPLÉ de l'idle : une session active au-delà de
    session_max_age (idle glissant, géré par le cookie) reste valide tant qu'elle
    est sous session_absolute_max_age — l'utilisateur en plein travail n'est pas
    coupé à 2 h."""
    from portal.auth.rbac import session_within_max_age
    from portal.settings import get_settings

    s = get_settings()
    assert s.session_absolute_max_age > s.session_max_age  # le plafond doit être + large
    # auth_time entre l'idle (2 h) et le plafond absolu (12 h) → toujours valide.
    between = int(time.time()) - s.session_max_age - 60
    assert session_within_max_age({"auth_time": between}) is True


def test_vscode_proxy_session_login_enforces_absolute_cap() -> None:
    """§032 — le proxy VS Code authentifie hors dep RBAC : il doit AUSSI appliquer
    le plafond absolu, sinon l'accès VS Code survivrait à l'expiration (fail-closed)."""
    from portal.routes.vscode_proxy import _session_login
    from portal.settings import get_settings

    fresh = _make_request({"user": {"login": "alice"}, "auth_time": int(time.time())})
    assert _session_login(fresh) == "alice"

    stale_ts = int(time.time()) - get_settings().session_absolute_max_age - 1
    stale = _make_request({"user": {"login": "alice"}, "auth_time": stale_ts})
    assert _session_login(stale) is None

    legacy = _make_request({"user": {"login": "alice"}})  # pas d'auth_time
    assert _session_login(legacy) is None


# ── Le cookie max_age provient bien de settings.session_max_age ──────────────


def test_cookie_max_age_uses_setting(tmp_path: Path) -> None:
    """create_app câble le max_age du cookie de session sur settings.session_max_age."""
    from starlette.middleware.sessions import SessionMiddleware

    import portal.settings as settings_mod

    prev_max_age = os.environ.get("SESSION_MAX_AGE")
    prev_secret = os.environ.get("SESSION_SECRET_KEY")
    prev_root = os.environ.get("PORTAL_DATA_ROOT")
    prev_kek = os.environ.get("PORTAL_VAULT_KEK")
    try:
        os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
        os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
        os.environ["SESSION_MAX_AGE"] = "1234"
        os.environ["PORTAL_VAULT_KEK"] = "0" * 64
        settings_mod._settings = None

        from portal.app import create_app

        app = create_app()
        max_ages = [
            m.kwargs["max_age"]
            for m in app.user_middleware
            if (m.cls is SessionMiddleware or issubclass(m.cls, SessionMiddleware))
            and "max_age" in getattr(m, "kwargs", {})
        ]
        assert max_ages == [1234]
    finally:
        for key, val in (
            ("SESSION_MAX_AGE", prev_max_age),
            ("SESSION_SECRET_KEY", prev_secret),
            ("PORTAL_DATA_ROOT", prev_root),
            ("PORTAL_VAULT_KEK", prev_kek),
        ):
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        settings_mod._settings = None
