from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class _RecordingClient:
    """Faux httpx.AsyncClient qui enregistre les URLs et sert le toc.txt."""

    def __init__(self, toc_text: str) -> None:
        self.toc_text = toc_text
        self.requested: list[str] = []

    async def get(self, url: str, timeout: float = 5.0, follow_redirects: bool = False):
        self.requested.append(url)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = self.toc_text
        return resp


@pytest.mark.parametrize(
    "source",
    ["https://ex.com/jinja/", "https://ex.com/jinja", "https://ex.com/jinja/toc.txt"],
)
async def test_preview_one_source_parses_and_builds_urls(source: str) -> None:
    from portal.routes.jinja_template_sources import _preview_one_source

    toc = (
        "test_host_available.fr.j2 | test_host_available | fr | Message dispo\n"
        "ligne invalide sans pipes\n"
        "bad.j2 | BAD KEY | fr | desc\n"  # key invalide -> skip
    )
    client = _RecordingClient(toc)
    results = await _preview_one_source(client, source)

    assert client.requested == ["https://ex.com/jinja/toc.txt"]
    assert len(results) == 1
    r = results[0]
    assert r["key"] == "test_host_available"
    assert r["culture"] == "fr"
    assert r["description"] == "Message dispo"
    assert r["source_url"] == "https://ex.com/jinja/test_host_available.fr.j2"
    assert r["source_base"] == "https://ex.com/jinja"


def _make_admin_app(tmp_path: Path):
    import portal.settings as mod
    from portal.routes.workspace_ops import _reset_service

    mod._settings = None
    os.environ["PORTAL_DATA_ROOT"] = str(tmp_path)
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-32chars-minimum!!"
    mod._settings = None
    _reset_service()

    from portal.app import create_app
    from portal.auth.rbac import UserInfo, require_admin

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: UserInfo(login="admin", roles=["admin"])
    return app


def _mock_http(body_text: str):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = body_text
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def test_import_creates_template(tmp_path: Path) -> None:
    app = _make_admin_app(tmp_path)
    http = _mock_http("Bonjour {{ user.login }}")
    with (
        TestClient(app) as client,
        patch("portal.routes.jinja_template_sources._check_ssrf", return_value=None),
        patch("portal.routes.jinja_template_sources.httpx.AsyncClient", return_value=http),
    ):
        resp = client.post(
            "/admin/jinja-template-sources/import",
            json={
                "source_url": "https://ex.com/jinja/welcome.fr.j2",
                "key": "welcome",
                "culture": "fr",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["key"] == "welcome"
    assert resp.json()["body"] == "Bonjour {{ user.login }}"


def test_import_conflict_without_overwrite(tmp_path: Path) -> None:
    app = _make_admin_app(tmp_path)
    http = _mock_http("v1")
    common = dict(
        source_url="https://ex.com/jinja/welcome.fr.j2", key="welcome", culture="fr"
    )
    with (
        TestClient(app) as client,
        patch("portal.routes.jinja_template_sources._check_ssrf", return_value=None),
        patch("portal.routes.jinja_template_sources.httpx.AsyncClient", return_value=http),
    ):
        first = client.post("/admin/jinja-template-sources/import", json=common)
        assert first.status_code == 200
        second = client.post("/admin/jinja-template-sources/import", json=common)
    assert second.status_code == 409
    assert second.json()["detail"] == "template_exists"


def test_import_overwrite(tmp_path: Path) -> None:
    app = _make_admin_app(tmp_path)
    with (
        TestClient(app) as client,
        patch("portal.routes.jinja_template_sources._check_ssrf", return_value=None),
    ):
        with patch(
            "portal.routes.jinja_template_sources.httpx.AsyncClient",
            return_value=_mock_http("v1"),
        ):
            client.post(
                "/admin/jinja-template-sources/import",
                json={"source_url": "https://ex.com/jinja/welcome.fr.j2",
                      "key": "welcome", "culture": "fr"},
            )
        with patch(
            "portal.routes.jinja_template_sources.httpx.AsyncClient",
            return_value=_mock_http("v2"),
        ):
            resp = client.post(
                "/admin/jinja-template-sources/import",
                json={"source_url": "https://ex.com/jinja/welcome.fr.j2",
                      "key": "welcome", "culture": "fr", "overwrite": True},
            )
    assert resp.status_code == 200
    assert resp.json()["body"] == "v2"
