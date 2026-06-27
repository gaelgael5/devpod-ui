# backend/tests/test_spa.py
"""Décision du fallback SPA : sert index.html pour les routes frontend, jamais pour
les routes backend atteintes par navigation navigateur (/auth/logout, /auth/callback…)."""
from __future__ import annotations

from portal.spa import should_serve_spa

_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


def test_serves_spa_for_frontend_routes() -> None:
    assert should_serve_spa("GET", "/", _HTML)
    assert should_serve_spa("GET", "/workspaces", _HTML)
    assert should_serve_spa("GET", "/auth/login", _HTML)
    assert should_serve_spa("GET", "/admin/hosts", _HTML)


def test_no_spa_for_backend_auth_routes() -> None:
    assert not should_serve_spa("GET", "/auth/logout", _HTML)
    assert not should_serve_spa("GET", "/auth/oidc", _HTML)
    assert not should_serve_spa("GET", "/auth/callback", _HTML)


def test_no_spa_for_oauth_backend_routes() -> None:
    # /oauth/authorize est une redirection navigateur vers l'AS (backend), pas une page React.
    assert not should_serve_spa("GET", "/oauth/authorize", _HTML)
    assert not should_serve_spa("GET", "/oauth/authorize?client_id=x", _HTML)
    assert not should_serve_spa("GET", "/.well-known/oauth-authorization-server", _HTML)
    assert not should_serve_spa("GET", "/mcp", _HTML)
    assert not should_serve_spa("GET", "/mcp/", _HTML)


def test_spa_still_serves_oauth_consent() -> None:
    # /oauth/consent EST une route React → doit être servie par le SPA.
    assert should_serve_spa("GET", "/oauth/consent", _HTML)


def test_no_spa_for_assets() -> None:
    assert not should_serve_spa("GET", "/assets/index-abc123.js", _HTML)
    assert not should_serve_spa("GET", "/favicon.ico", _HTML)


def test_no_spa_for_json_or_non_get() -> None:
    assert not should_serve_spa("GET", "/", "application/json")
    assert not should_serve_spa("POST", "/", _HTML)
