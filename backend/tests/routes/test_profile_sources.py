from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient


class _RecordingClient:
    """Faux httpx.AsyncClient qui enregistre les URLs demandées et sert le toc.txt."""

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
    [
        "https://example.com/profiles/",
        "https://example.com/profiles",
        "https://example.com/profiles/toc.txt",
    ],
)
async def test_preview_one_source_accepts_dir_and_tocurl(source: str) -> None:
    """Accepte le dossier comme l'URL complète du toc.txt, sans doubler /toc.txt."""
    from portal.routes.profile_sources import _preview_one_source

    client = _RecordingClient("python-dev.yaml | Python Dev | Profil Python | 8\n")
    results = await _preview_one_source(client, source)

    assert client.requested == ["https://example.com/profiles/toc.txt"]
    assert len(results) == 1
    assert results[0]["source_url"] == "https://example.com/profiles/python-dev.yaml"
    assert results[0]["source_base"] == "https://example.com/profiles"


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


def test_get_profile_sources_default(tmp_path: Path) -> None:
    """Sans fichier profile-sources.yaml, retourne la source par défaut (dev branch)."""
    from portal.routes.profile_sources import _DEFAULT_SOURCE

    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.get("/admin/profile-sources")
    assert resp.status_code == 200
    assert resp.json() == {"sources": [_DEFAULT_SOURCE]}


def test_put_profile_sources_saves(tmp_path: Path) -> None:
    """PUT /admin/profile-sources sauvegarde les URLs et les relit."""
    app = _make_admin_app(tmp_path)
    urls = ["https://example.com/profiles/"]
    with (
        TestClient(app) as client,
        patch("portal.routes.profile_sources._check_ssrf", return_value=None),
    ):
        resp = client.put(
            "/admin/profile-sources",
            json={"sources": urls},
        )
    assert resp.status_code == 200
    assert resp.json()["sources"] == urls
    saved = yaml.safe_load((tmp_path / "profile-sources.yaml").read_text(encoding="utf-8"))
    assert saved["sources"] == urls


def test_put_profile_sources_rejects_http(tmp_path: Path) -> None:
    """PUT /admin/profile-sources rejette les URLs non-HTTPS."""
    app = _make_admin_app(tmp_path)
    with TestClient(app) as client:
        resp = client.put(
            "/admin/profile-sources",
            json={"sources": ["http://example.com/profiles/"]},
        )
    assert resp.status_code == 422


def test_preview_profile_sources(tmp_path: Path) -> None:
    """GET preview fetche toc.txt et retourne les profils disponibles."""
    (tmp_path / "profile-sources.yaml").write_text(
        yaml.dump({"sources": ["https://example.com/profiles/"]}),
        encoding="utf-8",
    )
    toc_content = "python-dev.yaml | Python Dev | Profil Python | 8\n"
    toc_content += "invalid line without pipes\n"

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = toc_content

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    app = _make_admin_app(tmp_path)
    with (
        TestClient(app) as client,
        patch("portal.routes.profile_sources.httpx.AsyncClient", return_value=mock_client),
    ):
        resp = client.get("/admin/profile-sources/preview")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["profiles"]) == 1
    p = data["profiles"][0]
    assert p["filename"] == "python-dev.yaml"
    assert p["name"] == "Python Dev"
    assert p["description"] == "Profil Python"
    assert p["extension_count"] == 8
    assert p["source_url"] == "https://example.com/profiles/python-dev.yaml"


def test_import_profile_from_source(tmp_path: Path) -> None:
    """POST /admin/profile-sources/import crée un profil partagé."""
    import yaml as _yaml

    profile_yaml = _yaml.dump(
        {
            "name": "Python Dev",
            "description": "Profil Python",
            "extensions": ["ms-python.python"],
            "settings": {},
        }
    )

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = profile_yaml

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    app = _make_admin_app(tmp_path)
    with (
        TestClient(app) as client,
        patch("portal.routes.profile_sources._check_ssrf", return_value=None),
        patch("portal.routes.profile_sources.httpx.AsyncClient", return_value=mock_client),
    ):
        resp = client.post(
            "/admin/profile-sources/import",
            json={"source_url": "https://example.com/profiles/python-dev.yaml"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Python Dev"
    assert data["scope"] == "shared"
    assert data["slug"] == "python-dev"
    assert (tmp_path / "profiles" / "python-dev.yaml").is_file()


def test_import_profile_conflict(tmp_path: Path) -> None:
    """POST import retourne 409 si le slug existe déjà."""
    import yaml as _yaml

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "python-dev.yaml").write_text(
        _yaml.dump({"name": "Python Dev", "description": "", "extensions": [], "settings": {}}),
        encoding="utf-8",
    )

    profile_yaml = _yaml.dump(
        {
            "name": "Python Dev",
            "description": "Autre profil",
            "extensions": [],
            "settings": {},
        }
    )

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = profile_yaml

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    app = _make_admin_app(tmp_path)
    with (
        TestClient(app) as client,
        patch("portal.routes.profile_sources._check_ssrf", return_value=None),
        patch("portal.routes.profile_sources.httpx.AsyncClient", return_value=mock_client),
    ):
        resp = client.post(
            "/admin/profile-sources/import",
            json={"source_url": "https://example.com/profiles/python-dev.yaml"},
        )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "profile_slug_conflict"
