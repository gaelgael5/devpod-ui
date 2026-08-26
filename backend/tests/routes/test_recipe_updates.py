"""Mises a jour disponibles pour les recettes deja installees.

Une recette importee garde l'URL de son manifeste : c'est ce lien qui permet de
repondre a « ce que j'ai installe est-il encore a jour ? ». On interroge la
source, pas la galerie synchronisee — une recette venue d'une source depuis
retiree reste verifiable, et la reponse ne depend pas d'un rafraichissement.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from portal.auth.rbac import UserInfo
from portal.routes import recipe_sources as rs

_META = """
id: android-emulator
key: fe46f7ec-33f7-4252-b29c-cf224b8cd1af
version: 2.0.0
description: Chaine Android
"""


def _admin() -> UserInfo:
    return UserInfo(login="admin", roles=["admin"])


# ─── _remote_version ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lit_la_version_publiee(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fetch(http: Any, url: str) -> str:
        assert url.endswith("/recipe.meta.yaml")
        return _META

    monkeypatch.setattr(rs, "_fetch_text", _fetch)
    monkeypatch.setattr(rs, "check_ssrf", lambda url: None)

    assert await rs._remote_version(None, "https://x/recipes/android/install.sh") == "2.0.0"


@pytest.mark.asyncio
async def test_source_injoignable_rend_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Best-effort : une source morte rend la recette « indeterminee », elle
    n'affiche aucun bouton — elle ne fait pas echouer la page."""

    async def _fetch(http: Any, url: str) -> str:
        raise OSError("connection refused")

    monkeypatch.setattr(rs, "_fetch_text", _fetch)
    monkeypatch.setattr(rs, "check_ssrf", lambda url: None)

    assert await rs._remote_version(None, "https://x/recipes/android/install.sh") is None


@pytest.mark.asyncio
async def test_manifeste_casse_rend_none(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fetch(http: Any, url: str) -> str:
        return "ceci: n'est pas: un manifeste"

    monkeypatch.setattr(rs, "_fetch_text", _fetch)
    monkeypatch.setattr(rs, "check_ssrf", lambda url: None)

    assert await rs._remote_version(None, "https://x/recipes/android/install.sh") is None


@pytest.mark.asyncio
async def test_url_refusee_par_le_garde_ssrf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une source pointant vers le reseau interne ne doit pas etre interrogee —
    et pas davantage faire echouer la liste."""

    def _refuse(url: str) -> None:
        raise ValueError("adresse interne interdite")

    monkeypatch.setattr(rs, "check_ssrf", _refuse)

    assert await rs._remote_version(None, "http://169.254.169.254/install.sh") is None


# ─── list_recipe_updates ─────────────────────────────────────────────────────


def _cabler(
    monkeypatch: pytest.MonkeyPatch,
    installees: list[dict[str, str]],
    distantes: dict[str, str | None],
) -> None:
    async def _list(conn: Any) -> list[dict[str, str]]:
        return installees

    async def _version(http: Any, url: str) -> str | None:
        return distantes.get(url)

    import portal.db.recipes as dbr

    monkeypatch.setattr(dbr, "list_recipes_with_source", _list)
    monkeypatch.setattr(rs, "_remote_version", _version)


@pytest.mark.asyncio
async def test_signale_une_version_differente(monkeypatch: pytest.MonkeyPatch) -> None:
    _cabler(
        monkeypatch,
        [{"id": "android-emulator", "version": "1.0.0", "source_url": "https://x/a/install.sh"}],
        {"https://x/a/install.sh": "2.0.0"},
    )

    sorties = await rs.list_recipe_updates(user=_admin(), conn=None)

    assert sorties == [
        {
            "id": "android-emulator",
            "local_version": "1.0.0",
            "remote_version": "2.0.0",
            "source_url": "https://x/a/install.sh",
        }
    ]


@pytest.mark.asyncio
async def test_tait_une_version_identique(monkeypatch: pytest.MonkeyPatch) -> None:
    _cabler(
        monkeypatch,
        [{"id": "a", "version": "1.0.0", "source_url": "https://x/a/install.sh"}],
        {"https://x/a/install.sh": "1.0.0"},
    )

    assert await rs.list_recipe_updates(user=_admin(), conn=None) == []


@pytest.mark.asyncio
async def test_tait_une_version_indeterminee(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proposer une mise a jour vers une version inconnue ferait reimporter dans
    le vide."""
    _cabler(
        monkeypatch,
        [{"id": "a", "version": "1.0.0", "source_url": "https://x/a/install.sh"}],
        {"https://x/a/install.sh": None},
    )

    assert await rs.list_recipe_updates(user=_admin(), conn=None) == []


@pytest.mark.asyncio
async def test_aucune_recette_tracee_n_interroge_rien(monkeypatch: pytest.MonkeyPatch) -> None:
    appels: list[str] = []

    async def _version(http: Any, url: str) -> str | None:  # pragma: no cover
        appels.append(url)
        return None

    import portal.db.recipes as dbr

    async def _list(conn: Any) -> list[dict[str, str]]:
        return []

    monkeypatch.setattr(dbr, "list_recipes_with_source", _list)
    monkeypatch.setattr(rs, "_remote_version", _version)

    assert await rs.list_recipe_updates(user=_admin(), conn=None) == []
    assert appels == []


@pytest.mark.asyncio
async def test_trie_le_lot_sans_melanger_les_reponses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les sources sont interrogees en parallele : l'appariement version/recette
    doit suivre l'ordre d'entree, pas l'ordre d'arrivee des reponses."""
    _cabler(
        monkeypatch,
        [
            {"id": "a", "version": "1.0.0", "source_url": "https://x/a/install.sh"},
            {"id": "b", "version": "2.0.0", "source_url": "https://x/b/install.sh"},
            {"id": "c", "version": "3.0.0", "source_url": "https://x/c/install.sh"},
        ],
        {
            "https://x/a/install.sh": "1.0.0",  # a jour
            "https://x/b/install.sh": "2.1.0",  # a mettre a jour
            "https://x/c/install.sh": None,  # indeterminee
        },
    )

    sorties = await rs.list_recipe_updates(user=_admin(), conn=None)

    assert [s["id"] for s in sorties] == ["b"]
    assert sorties[0]["remote_version"] == "2.1.0"


# ─── update_recipe_from_source ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recette_inconnue_404(monkeypatch: pytest.MonkeyPatch) -> None:
    import portal.db.recipes as dbr

    async def _url(recipe_id: str, conn: Any) -> str | None:
        return None

    monkeypatch.setattr(dbr, "get_recipe_source_url", _url)

    with pytest.raises(HTTPException) as exc:
        await rs.update_recipe_from_source("nope", user=_admin(), conn=None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_recette_sans_origine_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une recette ecrite a la main n'a rien d'ou se mettre a jour : le dire
    vaut mieux que de tenter un telechargement depuis une URL vide."""
    import portal.db.recipes as dbr

    async def _url(recipe_id: str, conn: Any) -> str | None:
        return ""

    monkeypatch.setattr(dbr, "get_recipe_source_url", _url)

    with pytest.raises(HTTPException) as exc:
        await rs.update_recipe_from_source("maison", user=_admin(), conn=None)
    assert exc.value.status_code == 422
    assert "no source" in str(exc.value.detail)
