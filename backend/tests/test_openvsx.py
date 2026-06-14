"""Tests du client OpenVSX avec httpx.MockTransport (pas de réseau réel)."""

from __future__ import annotations

import httpx
import pytest

from portal.openvsx import OpenVsxClient, OpenVsxSettings, PluginDetail, PluginSearchResult

# ---------------------------------------------------------------------------
# Payloads mockés
# ---------------------------------------------------------------------------

SEARCH_PAYLOAD = {
    "totalSize": 1,
    "offset": 0,
    "extensions": [
        {
            "namespace": "ms-python",
            "name": "python",
            "displayName": "Python",
            "description": "Python language support",
            "version": "2024.0.1",
            "downloadCount": 100_000,
            "averageRating": 4.5,
            "files": {"icon": "https://open-vsx.org/icon.png"},
        }
    ],
}

DETAIL_PAYLOAD = {
    "namespace": "ms-python",
    "name": "python",
    "displayName": "Python",
    "description": "Python language support",
    "version": "2024.0.1",
    "downloadCount": 100_000,
    "averageRating": 4.5,
    "categories": ["Programming Languages"],
    "tags": ["python"],
    "files": {
        "icon": "https://open-vsx.org/icon.png",
        "readme": "https://open-vsx.org/readme.md",
        "license": "https://open-vsx.org/license.txt",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(base_url: str = "https://open-vsx.org", ttl: int = 3600) -> OpenVsxSettings:
    return OpenVsxSettings(base_url=base_url, timeout_s=10.0, cache_ttl_s=ttl)


def _make_client(handler, settings: OpenVsxSettings | None = None) -> OpenVsxClient:
    s = settings or _make_settings()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenVsxClient(s, http)


# ---------------------------------------------------------------------------
# search — nominal
# ---------------------------------------------------------------------------


async def test_search_nominal_mapping():
    """Payload mocké → items[0].id == 'ms-python.python', champs bien mappés."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SEARCH_PAYLOAD)

    client = _make_client(handler)
    result = await client.search("python")

    assert isinstance(result, PluginSearchResult)
    assert result.total == 1
    assert result.offset == 0
    assert len(result.items) == 1
    item = result.items[0]
    assert item.id == "ms-python.python"
    assert item.namespace == "ms-python"
    assert item.name == "python"
    assert item.display_name == "Python"
    assert item.downloads == 100_000
    assert item.rating == 4.5
    assert item.icon_url == "https://open-vsx.org/icon.png"


# ---------------------------------------------------------------------------
# search — tri
# ---------------------------------------------------------------------------


async def test_search_sort_popular_sends_download_count():
    """sort='popular' → querystring sortBy=downloadCount."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=SEARCH_PAYLOAD)

    client = _make_client(handler)
    await client.search("python", sort="popular")

    assert len(captured) == 1
    assert captured[0].url.params["sortBy"] == "downloadCount"


async def test_search_sort_recent_sends_timestamp():
    """sort='recent' → querystring sortBy=timestamp."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=SEARCH_PAYLOAD)

    client = _make_client(handler)
    await client.search("python", sort="recent")

    assert captured[0].url.params["sortBy"] == "timestamp"


# ---------------------------------------------------------------------------
# search — cache
# ---------------------------------------------------------------------------


async def test_search_cache_hits_transport_once():
    """Deux appels identiques → transport sollicité une seule fois."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=SEARCH_PAYLOAD)

    client = _make_client(handler)
    r1 = await client.search("python")
    r2 = await client.search("python")

    assert call_count == 1
    assert r1 is r2


async def test_search_different_queries_both_hit_transport():
    """Deux requêtes différentes → deux appels au transport."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=SEARCH_PAYLOAD)

    client = _make_client(handler)
    await client.search("python")
    await client.search("rust")

    assert call_count == 2


# ---------------------------------------------------------------------------
# search — erreur upstream
# ---------------------------------------------------------------------------


async def test_search_upstream_503_propagates_http_status_error():
    """Réponse 503 → HTTPStatusError propagée (pas swallowée)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    client = _make_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await client.search("python")


# ---------------------------------------------------------------------------
# detail
# ---------------------------------------------------------------------------


async def test_detail_extracts_readme_url_from_files():
    """detail() extrait readme_url depuis files.readme."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=DETAIL_PAYLOAD)

    client = _make_client(handler)
    detail = await client.detail("ms-python", "python")

    assert isinstance(detail, PluginDetail)
    assert detail.id == "ms-python.python"
    assert detail.readme_url == "https://open-vsx.org/readme.md"
    assert detail.categories == ["Programming Languages"]
    assert detail.tags == ["python"]
    assert detail.license == "https://open-vsx.org/license.txt"


# ---------------------------------------------------------------------------
# readme
# ---------------------------------------------------------------------------


async def test_readme_returns_empty_string_when_no_readme_url():
    """Sans files.readme dans le détail → retourne '' sans appel HTTP supplémentaire."""
    payload_no_readme = {**DETAIL_PAYLOAD, "files": {"icon": "https://open-vsx.org/icon.png"}}
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=payload_no_readme)

    client = _make_client(handler)
    content = await client.readme("ms-python", "python")

    assert content == ""
    assert call_count == 1  # uniquement l'appel detail, pas de fetch readme


async def test_readme_empty_result_is_cached():
    """La valeur '' est mise en cache — le deuxième appel ne re-fetche pas le détail."""
    payload_no_readme = {**DETAIL_PAYLOAD, "files": {"icon": "https://open-vsx.org/icon.png"}}
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=payload_no_readme)

    client = _make_client(handler)
    content1 = await client.readme("ms-python", "python")
    content2 = await client.readme("ms-python", "python")

    assert content1 == ""
    assert content2 == ""
    assert call_count == 1  # le deuxième appel utilise le cache readme, pas de re-fetch detail


async def test_readme_content_cached_after_first_fetch():
    """Deux appels readme identiques → le contenu est mis en cache (1 seul fetch markdown)."""
    readme_fetch_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal readme_fetch_count
        if "/api/" in str(request.url):
            # appel detail
            return httpx.Response(200, json=DETAIL_PAYLOAD)
        # appel readme content (https://open-vsx.org/readme.md)
        readme_fetch_count += 1
        return httpx.Response(200, text="# Python README")

    client = _make_client(handler)
    content1 = await client.readme("ms-python", "python")
    content2 = await client.readme("ms-python", "python")

    assert content1 == "# Python README"
    assert content2 == "# Python README"
    assert readme_fetch_count == 1  # contenu fetché une seule fois
