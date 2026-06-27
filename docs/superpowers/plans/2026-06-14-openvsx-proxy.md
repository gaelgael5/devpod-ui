# Proxy Open VSX — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exposer trois endpoints FastAPI (`/plugins/search`, `/plugins/{namespace}/{name}`, `/plugins/{namespace}/{name}/readme`) servant de proxy normalisé vers Open VSX, avec cache TTL mémoire et DTOs stables indépendants du schéma upstream.

**Architecture:** Client `OpenVsxClient` + DTOs dans `backend/src/portal/openvsx.py` (couche anti-corruption). Router FastAPI dans `backend/src/portal/routes/plugins.py`. Câblage lifespan dans `app.py` : un `httpx.AsyncClient` partagé est créé au démarrage, injecté via `dependency_overrides`. Cache `_TtlCache` par-process (aucune DB). Les routes exigent `require_user` (cohérent avec les conventions du projet).

**Tech Stack:** Python 3.12, FastAPI, pydantic v2, pydantic-settings v2, httpx async, structlog, pytest + pytest-asyncio (asyncio_mode=auto), `httpx.MockTransport` + `ASGITransport` pour les tests (pas de nouvelle dépendance).

---

## Fichiers touchés

| Action   | Fichier                                        | Rôle                                      |
|----------|------------------------------------------------|-------------------------------------------|
| Créer    | `backend/src/portal/openvsx.py`                | Client + DTOs + cache TTL                 |
| Créer    | `backend/src/portal/routes/plugins.py`         | Router FastAPI (3 endpoints)              |
| Modifier | `backend/src/portal/app.py`                    | Import router, lifespan AsyncClient       |
| Créer    | `backend/tests/test_openvsx.py`                | Tests unitaires client (MockTransport)    |
| Créer    | `backend/tests/routes/test_plugins.py`         | Tests des routes (ASGITransport)          |

---

## Contexte codebase (lire avant de coder)

- `backend/src/portal/app.py` — `create_app()` enregistre les routers ; `_lifespan()` gère le démarrage. `get_settings()` utilise un singleton module-level (`_settings`). Pas de `@lru_cache`.
- `backend/src/portal/auth/rbac.py` — `require_user` est async, lit `request.session`. `UserInfo` est un `dataclass(login: str, roles: list[str], sub: str)`.
- `backend/src/portal/routes/recipes.py` — exemple de router avec `require_user` ; suivre ce pattern.
- Tests asyncio sans décorateur (`asyncio_mode = "auto"` dans `pyproject.toml`).
- **respx est déjà en dev-deps** mais la spec demande `httpx.MockTransport` — s'y tenir.
- La spec utilise le préfixe `/api/plugins` ; **adapter en `/plugins`** (aucune autre route du projet n'utilise `/api/`).

---

## Task 1 : Client OpenVSX (`openvsx.py`) — TDD

**Files:**
- Create: `backend/src/portal/openvsx.py`
- Test: `backend/tests/test_openvsx.py`

- [ ] **Step 1 : Écrire les tests du client (fichier complet)**

```python
# backend/tests/test_openvsx.py
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
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd backend
uv run pytest tests/test_openvsx.py -v 2>&1 | head -30
```

Attendu : `ModuleNotFoundError: No module named 'portal.openvsx'`

- [ ] **Step 3 : Implémenter `openvsx.py`**

```python
# backend/src/portal/openvsx.py
"""Client Open VSX + couche anti-corruption.

Expose une API normalisée stable, indépendante du schéma upstream,
pour que le frontend ne dépende jamais du registre directement.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = structlog.get_logger(__name__)


class OpenVsxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENVSX_")

    base_url: str = "https://open-vsx.org"
    timeout_s: float = 10.0
    cache_ttl_s: int = 3600


class PluginSummary(BaseModel):
    id: str  # "{namespace}.{name}" — valeur qui ira dans customizations.vscode.extensions
    namespace: str
    name: str
    display_name: str
    description: str
    version: str
    downloads: int
    rating: float | None
    icon_url: str | None


class PluginSearchResult(BaseModel):
    total: int
    offset: int
    items: list[PluginSummary]


class PluginDetail(PluginSummary):
    categories: list[str]
    tags: list[str]
    license: str | None
    readme_url: str | None


_SORT_MAP: dict[str, str] = {
    "relevance": "relevance",
    "popular": "downloadCount",
    "recent": "timestamp",
    "rating": "averageRating",
}


class _TtlCache:
    """Cache mémoire (pas de DB, conforme aux principes du portail).

    Limite assumée : le cache est par-process. Avec plusieurs workers
    uvicorn, chaque worker a le sien. Sans gravité pour un proxy.
    """

    def __init__(self, ttl_s: int) -> None:
        self._ttl = ttl_s
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            hit = self._data.get(key)
            if hit and (time.monotonic() - hit[0]) < self._ttl:
                return hit[1]
            self._data.pop(key, None)
            return None

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._data[key] = (time.monotonic(), value)


class OpenVsxClient:
    def __init__(self, settings: OpenVsxSettings, http: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = http
        self._cache = _TtlCache(settings.cache_ttl_s)

    async def search(
        self, query: str, sort: str = "relevance", offset: int = 0, size: int = 24
    ) -> PluginSearchResult:
        sort_by = _SORT_MAP.get(sort, "relevance")
        key = f"search:{query}:{sort_by}:{offset}:{size}"
        if cached := await self._cache.get(key):
            return cached
        raw = await self._get(
            "/api/-/search",
            params={
                "query": query,
                "sortBy": sort_by,
                "sortOrder": "desc",
                "offset": offset,
                "size": size,
                "includeAllVersions": "false",
            },
        )
        result = PluginSearchResult(
            total=raw.get("totalSize", 0),
            offset=raw.get("offset", offset),
            items=[self._to_summary(e) for e in raw.get("extensions", [])],
        )
        await self._cache.set(key, result)
        return result

    async def detail(self, namespace: str, name: str) -> PluginDetail:
        key = f"detail:{namespace}.{name}"
        if cached := await self._cache.get(key):
            return cached
        raw = await self._get(f"/api/{namespace}/{name}")
        files: dict[str, str] = raw.get("files", {}) or {}
        detail = PluginDetail(
            id=f"{namespace}.{name}",
            namespace=namespace,
            name=name,
            display_name=raw.get("displayName") or name,
            description=raw.get("description", ""),
            version=raw.get("version", ""),
            downloads=raw.get("downloadCount", 0),
            rating=raw.get("averageRating"),
            icon_url=files.get("icon"),
            categories=raw.get("categories", []),
            tags=raw.get("tags", []),
            license=files.get("license"),
            readme_url=files.get("readme"),
        )
        await self._cache.set(key, detail)
        return detail

    async def readme(self, namespace: str, name: str) -> str:
        detail = await self.detail(namespace, name)
        if not detail.readme_url:
            return ""
        resp = await self._http.get(detail.readme_url, timeout=self._s.timeout_s)
        resp.raise_for_status()
        return resp.text

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._s.base_url}{path}"
        try:
            resp = await self._http.get(url, params=params, timeout=self._s.timeout_s)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            _log.warning("openvsx.http_error", url=url, status=exc.response.status_code)
            raise
        except httpx.HTTPError as exc:
            _log.error("openvsx.unreachable", url=url, error=str(exc))
            raise

    @staticmethod
    def _to_summary(e: dict[str, Any]) -> PluginSummary:
        ns, nm = e.get("namespace", ""), e.get("name", "")
        files: dict[str, str] = e.get("files", {}) or {}
        return PluginSummary(
            id=f"{ns}.{nm}",
            namespace=ns,
            name=nm,
            display_name=e.get("displayName") or nm,
            description=e.get("description", ""),
            version=e.get("version", ""),
            downloads=e.get("downloadCount", 0),
            rating=e.get("averageRating"),
            icon_url=files.get("icon"),
        )
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend
uv run pytest tests/test_openvsx.py -v
```

Attendu : tous les tests PASS (aucun réseau réel sollicité).

- [ ] **Step 5 : Lint + mypy**

```bash
cd backend
uv run ruff check src/portal/openvsx.py tests/test_openvsx.py
uv run ruff format src/portal/openvsx.py tests/test_openvsx.py
uv run mypy src/portal/openvsx.py
```

Corriger tout écart avant de continuer.

- [ ] **Step 6 : Commit**

```bash
git add backend/src/portal/openvsx.py backend/tests/test_openvsx.py
git commit -m "feat(plugins): client OpenVSX avec DTOs normalisés et cache TTL"
```

---

## Task 2 : Router FastAPI + câblage `app.py` — TDD

**Files:**
- Create: `backend/src/portal/routes/plugins.py`
- Modify: `backend/src/portal/app.py`
- Test: `backend/tests/routes/test_plugins.py`

- [ ] **Step 1 : Écrire les tests des routes (fichier complet)**

```python
# backend/tests/routes/test_plugins.py
"""Tests des routes /plugins/* via ASGITransport (pas de réseau réel, pas de lifespan)."""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

from portal.auth.rbac import UserInfo, require_user
from portal.openvsx import OpenVsxClient, PluginDetail, PluginSearchResult, PluginSummary
from portal.routes.plugins import get_openvsx, router as plugins_router

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
    application.dependency_overrides[require_user] = lambda: UserInfo(
        login="alice", roles=["dev"]
    )
    return application


@pytest.fixture
async def client(plugin_app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=plugin_app), base_url="http://test"
    ) as c:
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


async def test_detail_returns_200(
    client: AsyncClient, mock_openvsx_client: AsyncMock
) -> None:
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


async def test_readme_returns_markdown(
    client: AsyncClient, mock_openvsx_client: AsyncMock
) -> None:
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
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd backend
uv run pytest tests/routes/test_plugins.py -v 2>&1 | head -30
```

Attendu : `ImportError` ou `ModuleNotFoundError` sur `portal.routes.plugins`.

- [ ] **Step 3 : Implémenter `routes/plugins.py`**

```python
# backend/src/portal/routes/plugins.py
"""Routes proxy vers Open VSX : recherche, détail, readme.

Couche anti-corruption : le frontend ne voit que des DTOs normalisés
(PluginSummary, PluginDetail, PluginSearchResult), jamais le schéma brut.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..auth.rbac import UserInfo, require_user
from ..openvsx import OpenVsxClient, PluginDetail, PluginSearchResult

router = APIRouter(prefix="/plugins", tags=["plugins"])


def get_openvsx() -> OpenVsxClient:
    """Remplacée par dependency_overrides dans le lifespan (et dans les tests)."""
    raise NotImplementedError  # pragma: no cover


@router.get("/search", response_model=PluginSearchResult)
async def search_plugins(
    q: str = Query(min_length=1),
    sort: str = Query("relevance", pattern="^(relevance|popular|recent|rating)$"),
    offset: int = Query(0, ge=0),
    size: int = Query(24, ge=1, le=50),
    _user: UserInfo = Depends(require_user),
    client: OpenVsxClient = Depends(get_openvsx),
) -> PluginSearchResult:
    try:
        return await client.search(q, sort=sort, offset=offset, size=size)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Registre Open VSX injoignable")


@router.get("/{namespace}/{name}/readme")
async def plugin_readme(
    namespace: str,
    name: str,
    _user: UserInfo = Depends(require_user),
    client: OpenVsxClient = Depends(get_openvsx),
) -> Response:
    """Route déclarée avant /{namespace}/{name} pour éviter le shadowing par FastAPI."""
    try:
        md = await client.readme(namespace, name)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Readme indisponible")
    return Response(content=md, media_type="text/markdown; charset=utf-8")


@router.get("/{namespace}/{name}", response_model=PluginDetail)
async def plugin_detail(
    namespace: str,
    name: str,
    _user: UserInfo = Depends(require_user),
    client: OpenVsxClient = Depends(get_openvsx),
) -> PluginDetail:
    try:
        return await client.detail(namespace, name)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Plugin introuvable")
        raise HTTPException(status_code=502, detail="Registre Open VSX injoignable")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Registre Open VSX injoignable")
```

> **Attention ordre des routes** : `/{namespace}/{name}/readme` doit être déclaré **avant** `/{namespace}/{name}` sinon FastAPI route `readme` comme valeur de `name`.

- [ ] **Step 4 : Modifier `app.py` — ajouter import httpx + router + câblage lifespan**

Fichier cible : `backend/src/portal/app.py`

Ajout en tête des imports (après `from fastapi import FastAPI`) :

```python
import httpx
```

Ajout dans le bloc d'imports des routes (après `from .routes.workspace_ops import ...`) :

```python
from .routes.plugins import get_openvsx, router as plugins_router
```

Remplacement de `_lifespan` :

```python
@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from .openvsx import OpenVsxClient, OpenVsxSettings

    with contextlib.suppress(Exception):
        await _get_service().reconcile_port_forwards()
    async with httpx.AsyncClient(headers={"User-Agent": "devpod-ui/1.0"}) as http:
        client = OpenVsxClient(OpenVsxSettings(), http)
        app.dependency_overrides[get_openvsx] = lambda: client
        yield
```

Ajout dans `create_app()` — enregistrer `plugins_router` après `workspace_ops_router` (avant les routes admin) :

```python
    app.include_router(plugins_router)
```

Le fichier `app.py` complet après modifications :

```python
from __future__ import annotations

import contextlib
import httpx
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .auth.router import router as auth_router
from .routes.admin import router as admin_router
from .routes.me import router as me_router
from .routes.nodes import router as nodes_router
from .routes.plugins import get_openvsx, router as plugins_router
from .routes.proxmox import router as proxmox_router
from .routes.recipe_sources import router_admin as recipe_sources_admin_router
from .routes.recipes import router_admin as recipes_admin_router
from .routes.recipes import router_me as recipes_me_router
from .routes.recipes import router_public as recipes_public_router
from .routes.ssh_proxy import router as ssh_proxy_router
from .routes.static import router as static_router
from .routes.workspace_ops import _get_service
from .routes.workspace_ops import router as workspace_ops_router
from .settings import get_settings

_log = structlog.get_logger(__name__)

_SPA_INDEX = Path("static") / "index.html"
_NO_CACHE = "no-cache, no-store, must-revalidate"


class SPAMiddleware(BaseHTTPMiddleware):
    """Sert index.html pour les requêtes de navigation navigateur vers des routes frontend.

    Sans ce middleware, les routes API comme GET /admin/hypervisors prenaient la priorité
    sur le routeur React, renvoyant du JSON brut lors d'un rechargement de page.
    Critère : requête GET dont le Accept inclut text/html (navigation browser)
    et dont le chemin n'a pas d'extension (pas un asset JS/CSS/image).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method == "GET":
            accept = request.headers.get("Accept", "")
            path_last = request.url.path.split("/")[-1]
            is_browser_nav = "text/html" in accept and "application/json" not in accept
            is_page_route = "." not in path_last  # les assets ont une extension

            if is_browser_nav and is_page_route and _SPA_INDEX.is_file():
                return FileResponse(_SPA_INDEX, headers={"Cache-Control": _NO_CACHE})

        return await call_next(request)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from .openvsx import OpenVsxClient, OpenVsxSettings

    with contextlib.suppress(Exception):
        await _get_service().reconcile_port_forwards()
    async with httpx.AsyncClient(headers={"User-Agent": "devpod-ui/1.0"}) as http:
        client = OpenVsxClient(OpenVsxSettings(), http)
        app.dependency_overrides[get_openvsx] = lambda: client
        yield


def create_app() -> FastAPI:
    settings = get_settings()

    if not settings.session_secret_key:
        if settings.dev_mode:
            _log.warning(
                "session_secret_key_empty_dev_mode",
                msg="SESSION_SECRET_KEY not set — using insecure fallback (dev mode only)",
            )
        else:
            raise RuntimeError(
                "SESSION_SECRET_KEY must be set via environment variable or .env file. "
                "Starting without a session secret key is not allowed in production."
            )

    app = FastAPI(title="workspace-portal", version="0.1.0", lifespan=_lifespan)

    # Starlette insère chaque middleware en tête de liste (prepend).
    # Ordre d'exécution requête : SessionMiddleware → SPAMiddleware → Router.
    # SPAMiddleware court-circuite le routeur API pour les navigations browser.
    app.add_middleware(SPAMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key or "dev-only-insecure-key",
        session_cookie="portal_session",
        https_only=not settings.dev_mode,
        same_site="lax",
        max_age=86400,
    )
    app.include_router(auth_router)
    app.include_router(me_router, prefix="/me")
    app.include_router(workspace_ops_router, prefix="/me")
    app.include_router(recipes_public_router)
    app.include_router(recipes_me_router, prefix="/me")
    app.include_router(plugins_router)
    app.include_router(admin_router, prefix="/admin")
    app.include_router(nodes_router, prefix="/admin")
    app.include_router(proxmox_router, prefix="/admin")
    app.include_router(recipes_admin_router, prefix="/admin")
    app.include_router(recipe_sources_admin_router, prefix="/admin")
    app.include_router(ssh_proxy_router, prefix="/admin")
    # static_router en dernier : son catch-all /{full_path:path} ne doit pas
    # intercepter les routes API enregistrées avant lui.
    app.include_router(static_router)

    return app


app = create_app()
```

- [ ] **Step 5 : Vérifier que les tests des routes passent**

```bash
cd backend
uv run pytest tests/routes/test_plugins.py -v
```

Attendu : tous les tests PASS.

- [ ] **Step 6 : Lancer la suite complète pour détecter toute régression**

```bash
cd backend
uv run pytest -v 2>&1 | tail -20
```

Attendu : tous les tests antérieurs passent toujours.

- [ ] **Step 7 : Lint + mypy**

```bash
cd backend
uv run ruff check src/portal/routes/plugins.py src/portal/app.py tests/routes/test_plugins.py
uv run ruff format src/portal/routes/plugins.py src/portal/app.py tests/routes/test_plugins.py
uv run mypy src/portal/routes/plugins.py src/portal/app.py
```

Corriger tout écart avant de committer.

- [ ] **Step 8 : Commit**

```bash
git add \
  backend/src/portal/routes/plugins.py \
  backend/src/portal/app.py \
  backend/tests/routes/test_plugins.py
git commit -m "feat(plugins): router /plugins/* proxy Open VSX + câblage lifespan"
```

---

## Task 3 : Mise à jour `LESSONS.md`

**Files:**
- Modify: `LESSONS.md` (à la racine du dépôt)

- [ ] **Step 1 : Vérifier le schéma réel d'Open VSX (si réseau disponible)**

Consulter `https://open-vsx.org/swagger-ui/index.html` et comparer les champs suivants avec ce que le client attend :

| Champ attendu dans le code   | Champ dans la réponse Open VSX |
|------------------------------|-------------------------------|
| `totalSize`                  | `/api/-/search` → `totalSize` |
| `extensions[]`               | `/api/-/search` → `extensions` |
| `downloadCount`              | extension → `downloadCount`   |
| `averageRating`              | extension → `averageRating`   |
| `files.readme`               | `/api/{ns}/{name}` → `files.readme` |
| `files.icon`                 | → `files.icon`                |

Si un nom diffère : noter l'écart et adapter le mapping dans `openvsx.py`.

- [ ] **Step 2 : Ajouter les leçons dans `LESSONS.md`**

Ajouter à la fin du fichier (adapter si des écarts de schéma ont été constatés) :

```markdown
- [openvsx] Cache TTL par-process : avec plusieurs workers uvicorn, chaque worker a son propre cache. Acceptable pour un proxy Open VSX (pas d'état métier), mais à documenter si l'on passe à un déploiement multi-worker.
- [openvsx] Ordre routes FastAPI : déclarer /{ns}/{name}/readme AVANT /{ns}/{name} dans le router, sinon FastAPI interprète "readme" comme valeur du paramètre `name`.
- [openvsx] Préfixe routes : la spec suggérait /api/plugins mais le projet n'utilise pas de préfixe /api/ — adapté en /plugins pour cohérence.
```

Si des écarts de schéma ont été constatés lors du step 1, ajouter une ligne :
```markdown
- [openvsx] Écart schéma upstream : [décrire l'écart et l'adaptation effectuée].
```

- [ ] **Step 3 : Commit**

```bash
git add LESSONS.md
git commit -m "docs: LESSONS.md — cache par-process OpenVSX et ordre routes plugins"
```

---

## Definition of Done — checklist finale

Vérifier chaque point avant de déclarer le chantier terminé :

- [ ] `GET /plugins/search?q=python` répond 200 avec `PluginSearchResult` JSON
- [ ] `GET /plugins/search?q=` répond 422
- [ ] `GET /plugins/search?q=python&sort=invalid` répond 422
- [ ] `GET /plugins/{namespace}/{name}` répond 200 avec `PluginDetail` JSON
- [ ] upstream 404 → répond 404 `Plugin introuvable`
- [ ] upstream autre erreur → répond 502
- [ ] `GET /plugins/{namespace}/{name}/readme` répond 200 `text/markdown`
- [ ] `OPENVSX_BASE_URL` pris en compte via `OpenVsxSettings`
- [ ] Cache TTL fonctionnel (test double appel passe)
- [ ] Aucun champ brut Open VSX exposé (DTOs normalisés uniquement)
- [ ] `httpx.AsyncClient` fermé proprement en fin de lifespan
- [ ] `uv run pytest -v` : tous les tests passent, aucune régression
- [ ] `uv run ruff check` + `uv run mypy` : aucun écart
- [ ] `LESSONS.md` mis à jour
- [ ] Commits conventionnels FR sur branche `dev`
