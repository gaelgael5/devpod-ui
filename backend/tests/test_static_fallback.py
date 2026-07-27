"""spa_fallback : un asset versionné manquant renvoie 404, jamais index.html.

Régression : après un redéploiement, un onglet ouvert demande un ancien chunk
(`/assets/CredentialsPage-HASH.js`) qui n'existe plus. L'ancien fallback renvoyait
index.html (200, text/html) → le navigateur recevait du HTML au lieu d'un module JS
→ « Failed to fetch dynamically imported module ». Un 404 propre laisse le SPA gérer.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import portal.routes.static as static_mod


@pytest.fixture
def static_dir(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><html></html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-ABC123.js").write_text("export default 1")
    monkeypatch.setattr(static_mod, "_STATIC_DIR", tmp_path)
    return tmp_path


async def test_serves_existing_asset(static_dir) -> None:
    resp = await static_mod.spa_fallback("assets/app-ABC123.js")
    assert resp.status_code == 200


async def test_missing_asset_returns_404_not_index(static_dir) -> None:
    with pytest.raises(HTTPException) as exc:
        await static_mod.spa_fallback("assets/CredentialsPage-GONE99.js")
    assert exc.value.status_code == 404


async def test_missing_css_asset_returns_404(static_dir) -> None:
    with pytest.raises(HTTPException) as exc:
        await static_mod.spa_fallback("assets/index-GONE.css")
    assert exc.value.status_code == 404


async def test_navigation_route_still_serves_index(static_dir) -> None:
    """Une vraie route SPA (sans extension) retombe bien sur index.html."""
    resp = await static_mod.spa_fallback("git-credentials")
    assert resp.status_code == 200
