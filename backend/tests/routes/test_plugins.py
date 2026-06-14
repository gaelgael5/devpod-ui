"""Tests des routes /plugins/* via ASGITransport (pas de réseau réel, pas de lifespan)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from portal.auth.rbac import UserInfo, require_user
from portal.openvsx import OpenVsxClient, PluginDetail, PluginSearchResult, PluginSummary
from portal.routes.plugins import get_openvsx
from portal.routes.plugins import router as plugins_router

# ---------------------------------------------------------------------------
# Données de test
# ---------------------------------------------------------------------------

MOCK_SUMMARY = PluginSummary(
    id="ms-python.python",
    namespace="ms-python",
    name="python",
    display_name="Python",
    description="Python language support",
    version="2024.0.1",
    downloads=100_000,
    rating=4.5,
    icon_url=None,
)

MOCK_DETAIL = PluginDetail(
    id="ms-python.python",
    namespace="ms-python",
    name="python",
    display_name="Python",
    description="Python language support",
    version="2024.0.1",
    downloads=100_000,
    rating=4.5,
    icon_url=None,
    categories=["Programming Languages"],
    tags=["python"],
    license=None,
    readme_url="https://open-vsx.org/readme.md",
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_openvsx_client() -> AsyncMock:
    return AsyncMock(spec=OpenVsxClient)


@pytest.fixture
def plugin_app(mock_openvsx_client: AsyncMock) -> FastAPI:
    """App minimale avec uniquement le router plugins — évite les dépendances session/OIDC."""
    application = FastAPI()
    application.include_router(plugins_router)
    application.dependency_overrides[get_openvsx] = lambda: mock_openvsx_client
    application.dependency_overrides[require_user] = lambda: UserInfo(login="alice", roles=["dev"])
    return application


@pytest.fixture
async def client(plugin_app: FastAPI) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=plugin_app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# GET /plugins/search
# ---------------------------------------------------------------------------


async def test_search_returns_200_with_plugin_list(
    client: AsyncClient, mock_openvsx_client: AsyncMock
) -> None:
    mock_openvsx_client.search.return_value = PluginSearchResult(
        total=1, offset=0, items=[MOCK_SUMMARY]
    )
    response = await client.get("/plugins/search?q=python")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == "ms-python.python"


async def test_search_empty_q_returns_422(client: AsyncClient) -> None:
    response = await client.get("/plugins/search?q=")
    assert response.status_code == 422


async def test_search_invalid_sort_returns_422(client: AsyncClient) -> None:
    response = await client.get("/plugins/search?q=python&sort=unknown")
    assert response.status_code == 422


async def test_search_upstream_error_returns_502(
    client: AsyncClient, mock_openvsx_client: AsyncMock
) -> None:
    mock_openvsx_client.search.side_effect = httpx.HTTPError("connection refused")
    response = await client.get("/plugins/search?q=python")
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# GET /plugins/{namespace}/{name}
# ---------------------------------------------------------------------------


async def test_detail_returns_200(client: AsyncClient, mock_openvsx_client: AsyncMock) -> None:
    mock_openvsx_client.detail.return_value = MOCK_DETAIL
    response = await client.get("/plugins/ms-python/python")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "ms-python.python"
    assert body["readme_url"] == "https://open-vsx.org/readme.md"


async def test_detail_upstream_404_returns_404(
    client: AsyncClient, mock_openvsx_client: AsyncMock
) -> None:
    mock_openvsx_client.detail.side_effect = httpx.HTTPStatusError(
        "404",
        request=httpx.Request("GET", "https://open-vsx.org/api/ms-python/unknown"),
        response=httpx.Response(404),
    )
    response = await client.get("/plugins/ms-python/unknown")

    assert response.status_code == 404
    assert response.json()["detail"] == "Plugin introuvable"


async def test_detail_upstream_503_returns_502(
    client: AsyncClient, mock_openvsx_client: AsyncMock
) -> None:
    mock_openvsx_client.detail.side_effect = httpx.HTTPStatusError(
        "503",
        request=httpx.Request("GET", "https://open-vsx.org/api/ns/name"),
        response=httpx.Response(503),
    )
    response = await client.get("/plugins/ns/name")
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# GET /plugins/{namespace}/{name}/readme
# ---------------------------------------------------------------------------


async def test_readme_returns_markdown(client: AsyncClient, mock_openvsx_client: AsyncMock) -> None:
    mock_openvsx_client.readme.return_value = "# Python Extension\n\nDescription."
    response = await client.get("/plugins/ms-python/python/readme")

    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "# Python Extension" in response.text


async def test_readme_upstream_error_returns_502(
    client: AsyncClient, mock_openvsx_client: AsyncMock
) -> None:
    mock_openvsx_client.readme.side_effect = httpx.HTTPError("timeout")
    response = await client.get("/plugins/ms-python/python/readme")
    assert response.status_code == 502
