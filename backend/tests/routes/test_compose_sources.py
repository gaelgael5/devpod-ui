"""Tests de l'import galerie compose (routes/compose_sources.py)."""
from __future__ import annotations

import os
import socket
from pathlib import Path
from unittest.mock import patch

import respx
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

_MOCK_PUBLIC_ADDR = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def _write_global_config(tmp_path: Path) -> None:
    config = {
        "version": "1",
        "server": {
            "listen": "0.0.0.0:8080",
            "base_domain": "dev.yoops.org",
            "external_url": "https://dev.yoops.org",
            "dev_mode": True,
            "log": {"level": "info", "format": "text", "output": ""},
        },
        "auth": {
            "oidc": {
                "issuer": "https://kc.test",
                "client_id": "portal",
                "client_secret": "",
                "scopes": ["openid"],
                "role_claim": "realm_access.roles",
                "admin_role": "admin",
                "user_role": "dev",
                "username_claim": "preferred_username",
            }
        },
        "secrets": {
            "backend": "inline",
            "harpocrate": {"url": "", "api_key": "", "base_path": "devpod"},
        },
        "devpod": {
            "binary": "devpod",
            "defaults": {"ide": "openvscode", "idle_timeout": "2h", "dotfiles": ""},
            "client_cert_path": "/data/certs/portal",
        },
        "hosts": [],
        "caddy": {"admin_api": ""},
        "cloudflare_manager": {"url": "", "api_key": ""},
    }
    (tmp_path / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8"
    )


def _make_admin_app(tmp_path: Path) -> FastAPI:
    import portal.settings as mod
    from portal.routes.workspace_ops import _reset_service

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None
    _reset_service()

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_admin, require_user

    app = create_app()
    admin_user = UserInfo(login="admin", roles=["admin"])
    app.dependency_overrides[require_admin] = lambda: admin_user
    app.dependency_overrides[require_user] = lambda: admin_user
    return app


_ALLOY_META = """\
id: alloy-collector
name: Collecteur de logs (Alloy)
description: Collecte les logs et les pousse vers Loki.
version: "1"
tags: [observabilité, logs]
extra_files: [config.alloy]
"""

_ALLOY_COMPOSE = """\
services:
  alloy:
    image: grafana/alloy:v1.5.1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /var/log:/var/log:ro
      - /run/log/journal:/run/log/journal:ro
      - /etc/machine-id:/etc/machine-id:ro
      - alloy_data:/var/lib/alloy/data
volumes:
  alloy_data:
"""

_ALLOY_CONFIG = "// config alloy factice\n"


@respx.mock
def test_import_fetches_extra_files_declared_in_meta(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)

    base = "https://example.com/templates/alloy-collector"
    respx.get(f"{base}/meta.yaml").mock(return_value=Response(200, text=_ALLOY_META))
    respx.get(f"{base}/compose.yml").mock(return_value=Response(200, text=_ALLOY_COMPOSE))
    respx.get(f"{base}/config.alloy").mock(return_value=Response(200, text=_ALLOY_CONFIG))

    with (
        patch("portal.routes.compose_sources._socket.getaddrinfo", return_value=_MOCK_PUBLIC_ADDR),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/admin/compose-sources/import", json={"source_url": f"{base}/compose.yml"}
        )

        assert resp.status_code == 201, resp.text
        assert resp.json()["id"] == "alloy-collector"

        listing = client.get("/api/compose/templates").json()

    tpl = next(t for t in listing if t["id"] == "alloy-collector")
    assert tpl["extra_files"] == {"config.alloy": _ALLOY_CONFIG}
    assert tpl["source"] == "imported"


@respx.mock
def test_import_allows_system_bind_mounts_via_whitelist(tmp_path: Path) -> None:
    # Sans le fix : validate_template n'était jamais appelée à l'import (aucun
    # garde-fou) ; avec le fix, la whitelist système doit laisser passer ce
    # template précis (mêmes 4 chemins que le collecteur builtin).
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)

    base = "https://example.com/templates/alloy-collector"
    respx.get(f"{base}/meta.yaml").mock(return_value=Response(200, text=_ALLOY_META))
    respx.get(f"{base}/compose.yml").mock(return_value=Response(200, text=_ALLOY_COMPOSE))
    respx.get(f"{base}/config.alloy").mock(return_value=Response(200, text=_ALLOY_CONFIG))

    with (
        patch("portal.routes.compose_sources._socket.getaddrinfo", return_value=_MOCK_PUBLIC_ADDR),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/admin/compose-sources/import", json={"source_url": f"{base}/compose.yml"}
        )
    assert resp.status_code == 201, resp.text


@respx.mock
def test_import_rejects_non_whitelisted_bind_mount(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)

    base = "https://example.com/templates/evil"
    meta = "id: evil\nname: Evil\nversion: \"1\"\n"
    compose = (
        "services:\n  svc:\n    image: x:1.0.0\n"
        "    volumes:\n      - /etc/passwd:/etc/passwd:ro\n"
    )
    respx.get(f"{base}/meta.yaml").mock(return_value=Response(200, text=meta))
    respx.get(f"{base}/compose.yml").mock(return_value=Response(200, text=compose))

    with (
        patch("portal.routes.compose_sources._socket.getaddrinfo", return_value=_MOCK_PUBLIC_ADDR),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/admin/compose-sources/import", json={"source_url": f"{base}/compose.yml"}
        )

    assert resp.status_code == 422
    assert "bind-mount" in resp.json()["detail"]


@respx.mock
def test_import_rejects_extra_file_path_traversal(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)

    base = "https://example.com/templates/evil2"
    meta = 'id: evil2\nname: Evil2\nversion: "1"\nextra_files: ["../../etc/passwd"]\n'
    compose = "services:\n  svc:\n    image: x:1.0.0\n"
    respx.get(f"{base}/meta.yaml").mock(return_value=Response(200, text=meta))
    respx.get(f"{base}/compose.yml").mock(return_value=Response(200, text=compose))

    with (
        patch("portal.routes.compose_sources._socket.getaddrinfo", return_value=_MOCK_PUBLIC_ADDR),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/admin/compose-sources/import", json={"source_url": f"{base}/compose.yml"}
        )

    assert resp.status_code == 422


@respx.mock
def test_import_missing_extra_file_returns_502(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)

    base = "https://example.com/templates/broken"
    meta = 'id: broken\nname: Broken\nversion: "1"\nextra_files: ["missing.conf"]\n'
    compose = "services:\n  svc:\n    image: x:1.0.0\n"
    respx.get(f"{base}/meta.yaml").mock(return_value=Response(200, text=meta))
    respx.get(f"{base}/compose.yml").mock(return_value=Response(200, text=compose))
    respx.get(f"{base}/missing.conf").mock(return_value=Response(404))

    with (
        patch("portal.routes.compose_sources._socket.getaddrinfo", return_value=_MOCK_PUBLIC_ADDR),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/admin/compose-sources/import", json={"source_url": f"{base}/compose.yml"}
        )

    assert resp.status_code == 502


@respx.mock
def test_import_now_rejects_undeclared_variable(tmp_path: Path) -> None:
    # Avant le fix : import_compose_from_source n'appelait jamais validate_template
    # → ce template passait silencieusement (201) malgré WEB_PORT non déclaré.
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)

    base = "https://example.com/templates/undeclared"
    meta = 'id: undeclared\nname: Undeclared\nversion: "1"\n'
    compose = 'services:\n  web:\n    image: nginx:1.27.0\n    ports:\n      - "${WEB_PORT}:80"\n'
    respx.get(f"{base}/meta.yaml").mock(return_value=Response(200, text=meta))
    respx.get(f"{base}/compose.yml").mock(return_value=Response(200, text=compose))

    with (
        patch("portal.routes.compose_sources._socket.getaddrinfo", return_value=_MOCK_PUBLIC_ADDR),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/admin/compose-sources/import", json={"source_url": f"{base}/compose.yml"}
        )

    assert resp.status_code == 422
    assert "non déclarées" in resp.json()["detail"]


@respx.mock
def test_import_without_extra_files_still_works(tmp_path: Path) -> None:
    _write_global_config(tmp_path)
    app = _make_admin_app(tmp_path)

    base = "https://example.com/templates/simple"
    meta = (
        'id: simple\nname: Simple\nversion: "1"\n'
        "parameters:\n"
        "  - key: WEB_PORT\n    label: Port\n    type: port\n    required: true\n"
    )
    compose = 'services:\n  web:\n    image: nginx:1.27.0\n    ports:\n      - "${WEB_PORT}:80"\n'
    respx.get(f"{base}/meta.yaml").mock(return_value=Response(200, text=meta))
    respx.get(f"{base}/compose.yml").mock(return_value=Response(200, text=compose))

    with (
        patch("portal.routes.compose_sources._socket.getaddrinfo", return_value=_MOCK_PUBLIC_ADDR),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/admin/compose-sources/import", json={"source_url": f"{base}/compose.yml"}
        )

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "simple"
