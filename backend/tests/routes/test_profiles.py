"""Tests des routes /profiles/* et /admin/profiles/* via ASGITransport."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from portal.auth.rbac import UserInfo, require_admin, require_user
from portal.profiles.models import Profile, ProfileBody, ProfileSummary
from portal.profiles.repository import ProfileError, ProfileRepository
from portal.routes.profiles import get_repo, router, router_admin

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ALICE_USER = UserInfo(login="alice", roles=["dev"])
ADMIN_USER = UserInfo(login="admin", roles=["admin"])

MOCK_SUMMARY = ProfileSummary(
    slug="frontend-react",
    scope="user",
    name="Frontend React",
    description="",
    extension_count=1,
    editable=True,
)

MOCK_PROFILE = Profile(
    slug="frontend-react",
    scope="user",
    name="Frontend React",
    description="",
    extensions=["esbenp.prettier-vscode"],
    settings={},
)


@pytest.fixture
def mock_repo() -> MagicMock:
    return MagicMock(spec=ProfileRepository)


@pytest.fixture
def profiles_app(mock_repo: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.include_router(router_admin, prefix="/admin")
    app.dependency_overrides[require_user] = lambda: ALICE_USER
    app.dependency_overrides[require_admin] = lambda: ADMIN_USER
    app.dependency_overrides[get_repo] = lambda: mock_repo
    return app


@pytest.fixture
async def client(profiles_app: FastAPI) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=profiles_app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# GET /profiles
# ---------------------------------------------------------------------------

async def test_list_returns_200(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.list.return_value = [MOCK_SUMMARY]
    response = await client.get("/profiles")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["slug"] == "frontend-react"
    mock_repo.list.assert_called_once_with("alice", False)


# ---------------------------------------------------------------------------
# GET /profiles/{scope}/{slug}
# ---------------------------------------------------------------------------

async def test_get_returns_profile(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.get.return_value = MOCK_PROFILE
    response = await client.get("/profiles/user/frontend-react")
    assert response.status_code == 200
    assert response.json()["slug"] == "frontend-react"


async def test_get_not_found_returns_404(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.get.side_effect = ProfileError("not_found")
    response = await client.get("/profiles/user/nonexistent")
    assert response.status_code == 404


async def test_get_invalid_scope_returns_422(client: AsyncClient) -> None:
    response = await client.get("/profiles/invalid/slug")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /profiles
# ---------------------------------------------------------------------------

async def test_create_returns_201(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.create.return_value = MOCK_PROFILE
    response = await client.post(
        "/profiles",
        json={"name": "Frontend React", "extensions": ["esbenp.prettier-vscode"]},
    )
    assert response.status_code == 201
    assert response.json()["slug"] == "frontend-react"


# ---------------------------------------------------------------------------
# PUT /profiles/{slug}
# ---------------------------------------------------------------------------

async def test_update_returns_200(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.update.return_value = MOCK_PROFILE
    response = await client.put(
        "/profiles/frontend-react",
        json={"name": "Frontend React", "extensions": []},
    )
    assert response.status_code == 200


async def test_update_not_found_returns_404(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.update.side_effect = ProfileError("not_found")
    response = await client.put(
        "/profiles/nonexistent",
        json={"name": "X", "extensions": []},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /profiles/{slug}
# ---------------------------------------------------------------------------

async def test_delete_returns_204(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.delete.return_value = None
    response = await client.delete("/profiles/frontend-react")
    assert response.status_code == 204


async def test_delete_not_found_returns_404(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.delete.side_effect = ProfileError("not_found")
    response = await client.delete("/profiles/nonexistent")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /profiles/shared/{slug}/fork
# ---------------------------------------------------------------------------

async def test_fork_returns_201(client: AsyncClient, mock_repo: MagicMock) -> None:
    forked = Profile(
        slug="frontend-react-2",
        scope="user",
        name="Frontend React",
        description="",
        extensions=["esbenp.prettier-vscode"],
        settings={},
    )
    mock_repo.fork.return_value = forked
    response = await client.post("/profiles/shared/frontend-react/fork")
    assert response.status_code == 201
    assert response.json()["scope"] == "user"
    mock_repo.fork.assert_called_once_with("alice", "frontend-react")


async def test_fork_not_found_returns_404(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.fork.side_effect = ProfileError("not_found")
    response = await client.post("/profiles/shared/nonexistent/fork")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Routes admin
# ---------------------------------------------------------------------------

async def test_admin_create_shared_returns_201(client: AsyncClient, mock_repo: MagicMock) -> None:
    shared = Profile(
        slug="shared-profile",
        scope="shared",
        name="Shared",
        description="",
        extensions=[],
        settings={},
    )
    mock_repo.create_shared.return_value = shared
    response = await client.post("/admin/profiles", json={"name": "Shared", "extensions": []})
    assert response.status_code == 201
    assert response.json()["scope"] == "shared"


async def test_admin_update_shared_returns_200(client: AsyncClient, mock_repo: MagicMock) -> None:
    shared = Profile(
        slug="shared-profile",
        scope="shared",
        name="Shared Updated",
        description="",
        extensions=[],
        settings={},
    )
    mock_repo.update_shared.return_value = shared
    response = await client.put(
        "/admin/profiles/shared-profile",
        json={"name": "Shared Updated", "extensions": []},
    )
    assert response.status_code == 200


async def test_admin_delete_shared_returns_204(client: AsyncClient, mock_repo: MagicMock) -> None:
    mock_repo.delete_shared.return_value = None
    response = await client.delete("/admin/profiles/shared-profile")
    assert response.status_code == 204
