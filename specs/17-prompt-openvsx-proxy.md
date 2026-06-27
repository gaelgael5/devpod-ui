# Chantier — Proxy FastAPI vers Open VSX (recherche + détail de plugins)

> Tu travailles sur le dépôt **devpod-ui** (portail self-hosted qui pilote DevPod).
> Ce chantier est la fondation backend de la future page « Profil VSCode ».
> Implémente **uniquement le proxy** ; l'UX et le CRUD des profils feront l'objet de chantiers séparés.

## 0. Préalables (à faire avant toute écriture)

1. Lis `CLAUDE.md` et `LESSONS.md` à la racine, puis le contexte transversal (`README.md`, et dans `specs/` : `01_ARCHITECTURE.md`, `02_CONFIG_REFERENCE.md`, `03_PITFALLS.md` s'ils existent). **Respecte la structure et les conventions existantes** ; les chemins proposés ci-dessous sont une cible à adapter à l'arborescence réelle de `backend/`.
2. Travaille **exclusivement sur la branche `dev`**.
3. **Vérifie le contrat de l'API Open VSX** sur `https://open-vsx.org/swagger-ui/index.html` (endpoints `/api/-/search` et `/api/{namespace}/{name}`). Le code de référence ci-dessous reflète la forme connue, mais c'est de l'upstream : si un nom de champ diffère, **adapte le mapping et consigne l'écart dans `LESSONS.md`**.
4. N'introduis **aucune nouvelle dépendance runtime** hors stack imposée (FastAPI, pydantic v2, pydantic-settings, httpx, structlog). Pour les tests, utilise `httpx.MockTransport` (pas de nouvelle dépendance) plutôt que respx.

## 1. Objectif

Exposer trois routes REST qui servent de proxy normalisé vers le registre Open VSX, pour alimenter la recherche de plugins « façon VS Code » du frontend :

- recherche avec tri et pagination,
- détail d'un plugin,
- README rendu côté serveur.

## 2. Contrainte métier non négociable

openvscode-server (l'IDE lancé par DevPod) résout les extensions sur **Open VSX**, **pas** sur le marketplace Microsoft. La recherche **doit donc interroger Open VSX**, sinon l'utilisateur sélectionnera des plugins qui échoueront à l'installation. Ne tape jamais `marketplace.visualstudio.com`.

## 3. Décisions d'architecture (à respecter)

1. **Couche anti-corruption.** Le frontend ne voit que des DTO normalisés et stables (`PluginSummary`, `PluginSearchResult`, `PluginDetail`), jamais le schéma brut d'Open VSX. Objectif : pouvoir basculer vers un registre Open VSX self-hosted sans toucher au frontend.
2. **`base_url` configurable** via `OPENVSX_BASE_URL` (défaut `https://open-vsx.org`). Le pivot self-host = une variable d'env.
3. **Cache TTL en mémoire** (défaut 1 h). **Pas de base de données** (principe du portail). Assume que le cache est par-process : c'est acceptable pour un proxy, ce n'est pas de l'état métier. Documente cette limite en commentaire.
4. **README proxifié côté serveur** (évite les soucis CORS sur `open-vsx.org`). Le frontend reçoit du markdown brut.
5. **Le champ `id` d'un plugin = `"{namespace}.{name}"`** : c'est exactement la valeur qui ira plus tard dans `customizations.vscode.extensions`. Ce contrat doit rester intact.

## 4. Arborescence cible (à adapter)

```
backend/app/services/openvsx.py   # client + DTO + cache TTL
backend/app/api/plugins.py        # router FastAPI
backend/tests/test_openvsx.py     # tests du client (mock transport)
backend/tests/test_plugins_api.py # tests des routes
```

Câble le router dans le `main.py`/factory existant via le lifespan (voir §7).

## 5. Spécification — `services/openvsx.py`

Implémentation de référence (respecte la signature et le comportement ; reformate selon le linter du projet) :

```python
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

log = structlog.get_logger(__name__)


class OpenVsxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENVSX_")
    base_url: str = "https://open-vsx.org"
    timeout_s: float = 10.0
    cache_ttl_s: int = 3600


class PluginSummary(BaseModel):
    id: str            # "namespace.name" -> va tel quel dans devcontainer.json
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


_SORT_MAP = {
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
                "query": query, "sortBy": sort_by, "sortOrder": "desc",
                "offset": offset, "size": size, "includeAllVersions": "false",
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
        files = raw.get("files", {}) or {}
        detail = PluginDetail(
            id=f"{namespace}.{name}", namespace=namespace, name=name,
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

    async def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._s.base_url}{path}"
        try:
            resp = await self._http.get(url, params=params, timeout=self._s.timeout_s)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            log.warning("openvsx.http_error", url=url, status=exc.response.status_code)
            raise
        except httpx.HTTPError as exc:
            log.error("openvsx.unreachable", url=url, error=str(exc))
            raise

    @staticmethod
    def _to_summary(e: dict) -> PluginSummary:
        ns, nm = e.get("namespace", ""), e.get("name", "")
        return PluginSummary(
            id=f"{ns}.{nm}", namespace=ns, name=nm,
            display_name=e.get("displayName") or nm,
            description=e.get("description", ""),
            version=e.get("version", ""),
            downloads=e.get("downloadCount", 0),
            rating=e.get("averageRating"),
            icon_url=(e.get("files", {}) or {}).get("icon"),
        )
```

## 6. Spécification — `api/plugins.py`

```python
"""Routes proxy vers Open VSX : recherche, détail, readme."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.services.openvsx import OpenVsxClient, PluginDetail, PluginSearchResult

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


def get_openvsx() -> OpenVsxClient:  # injecté au lifespan
    raise NotImplementedError


@router.get("/search", response_model=PluginSearchResult)
async def search_plugins(
    q: str = Query(min_length=1),
    sort: str = Query("relevance", pattern="^(relevance|popular|recent|rating)$"),
    offset: int = Query(0, ge=0),
    size: int = Query(24, ge=1, le=50),
    client: OpenVsxClient = Depends(get_openvsx),
) -> PluginSearchResult:
    try:
        return await client.search(q, sort=sort, offset=offset, size=size)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Registre Open VSX injoignable")


@router.get("/{namespace}/{name}", response_model=PluginDetail)
async def plugin_detail(
    namespace: str, name: str, client: OpenVsxClient = Depends(get_openvsx)
) -> PluginDetail:
    try:
        return await client.detail(namespace, name)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Plugin introuvable")
        raise HTTPException(status_code=502, detail="Registre Open VSX injoignable")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Registre Open VSX injoignable")


@router.get("/{namespace}/{name}/readme")
async def plugin_readme(
    namespace: str, name: str, client: OpenVsxClient = Depends(get_openvsx)
) -> Response:
    try:
        md = await client.readme(namespace, name)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Readme indisponible")
    return Response(content=md, media_type="text/markdown; charset=utf-8")
```

## 7. Câblage (lifespan)

Un seul `httpx.AsyncClient` partagé, fermé proprement à l'arrêt. Adapte au pattern de factory existant :

```python
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from app.services.openvsx import OpenVsxClient, OpenVsxSettings
from app.api import plugins


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = OpenVsxSettings()
    async with httpx.AsyncClient(headers={"User-Agent": "devpod-ui"}) as http:
        client = OpenVsxClient(settings, http)
        app.dependency_overrides[plugins.get_openvsx] = lambda: client
        yield


app = FastAPI(lifespan=lifespan)
app.include_router(plugins.router)
```

## 8. Tests requis (`pytest` + `pytest-asyncio`, mock via `httpx.MockTransport`)

Construis un `httpx.AsyncClient(transport=httpx.MockTransport(handler))` et injecte-le dans `OpenVsxClient`. Pour les tests de routes, surcharge `get_openvsx` via `app.dependency_overrides`.

**`test_openvsx.py`**
- `search` nominal : un payload mocké à 1 extension → `items[0].id == "ms-python.python"`, mapping des champs correct.
- mapping du tri : `sort="popular"` envoie bien `sortBy=downloadCount` dans la requête (inspecte la query de la requête mockée).
- cache : deux appels identiques → le transport n'est sollicité **qu'une fois**.
- erreur upstream (503) → `httpx.HTTPStatusError`/`HTTPError` propagée.
- `detail` : extrait correctement `readme_url` depuis `files.readme`.
- `readme` : sans `files.readme` → retourne `""` (pas d'appel HTTP supplémentaire).

**`test_plugins_api.py`** (via `httpx.AsyncClient`/`ASGITransport` sur l'app)
- `GET /api/plugins/search?q=python` → 200 + structure `PluginSearchResult`.
- `q` vide → 422 (validation).
- `sort` invalide → 422.
- détail sur upstream 404 → 404 `Plugin introuvable`.
- upstream injoignable → 502.

Vise une couverture nette des branches d'erreur. Pas de réseau réel dans les tests.

## 9. Conventions à respecter (rappel)

- Branche `dev` uniquement.
- **Commits conventionnels en français** (ex. `feat(plugins): proxy Open VSX recherche et détail`).
- Aucun fichier > 300 lignes.
- pydantic v2 + pydantic-settings, httpx async, structlog en logs JSON.
- Pas de DB, pas de SQLAlchemy/Alembic.
- Typage strict, pas de `Any` non justifié hors parsing upstream.

## 10. Definition of Done

- [ ] Les 3 endpoints répondent et sont typés (`response_model`).
- [ ] DTO normalisés ; aucun champ brut Open VSX exposé au frontend.
- [ ] `OPENVSX_BASE_URL` pris en compte (testé en surchargeant l'env/les settings).
- [ ] Cache TTL fonctionnel (test du double appel).
- [ ] README proxifié en `text/markdown`.
- [ ] Erreurs upstream mappées (404 → 404, autre → 502).
- [ ] Tests verts, sans accès réseau réel.
- [ ] Router câblé au lifespan, `AsyncClient` fermé proprement.
- [ ] Écart éventuel avec le swagger Open VSX consigné dans `LESSONS.md`.
- [ ] Commit(s) conventionnel(s) FR sur `dev`.

## 11. Après implémentation

Mets à jour `LESSONS.md` avec : tout écart de schéma constaté sur Open VSX, et la décision de cache par-process (pour le futur chantier UX/scale).
