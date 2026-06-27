# backend/tests/exposure/test_verify_uri.py
"""URI du forward_auth Caddy : appel INTERNE au portail (réseau Docker), jamais
via l'URL publique (évite l'aller-retour Cloudflare et une boucle réseau)."""
from __future__ import annotations

from portal.exposure.caddy import internal_verify_uri


def test_default_listen_port() -> None:
    assert internal_verify_uri("portal", "0.0.0.0:8080") == (
        "http://portal:8080/auth/caddy/verify"
    )


def test_custom_host_and_port() -> None:
    assert internal_verify_uri("portal-svc", "127.0.0.1:9000") == (
        "http://portal-svc:9000/auth/caddy/verify"
    )
