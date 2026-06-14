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
    model_config = SettingsConfigDict(env_prefix="OPENVSX_", extra="forbid")

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


class _TtlCache[T]:
    """Cache mémoire (pas de DB, conforme aux principes du portail).

    Limite assumée : le cache est par-process. Avec plusieurs workers
    uvicorn, chaque worker a le sien. Sans gravité pour un proxy.
    """

    def __init__(self, ttl_s: int) -> None:
        self._ttl = ttl_s
        self._data: dict[str, tuple[float, T]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> T | None:
        async with self._lock:
            hit = self._data.get(key)
            if hit and (time.monotonic() - hit[0]) < self._ttl:
                return hit[1]
            self._data.pop(key, None)
            return None

    async def set(self, key: str, value: T) -> None:
        async with self._lock:
            self._data[key] = (time.monotonic(), value)


class OpenVsxClient:
    def __init__(self, settings: OpenVsxSettings, http: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = http
        self._search_cache: _TtlCache[PluginSearchResult] = _TtlCache(settings.cache_ttl_s)
        self._detail_cache: _TtlCache[PluginDetail] = _TtlCache(settings.cache_ttl_s)
        self._readme_cache: _TtlCache[str] = _TtlCache(settings.cache_ttl_s)

    async def search(
        self, query: str, sort: str = "relevance", offset: int = 0, size: int = 24
    ) -> PluginSearchResult:
        sort_by = _SORT_MAP.get(sort, "relevance")
        key = f"search:{query}:{sort_by}:{offset}:{size}"
        if cached := await self._search_cache.get(key):
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
        await self._search_cache.set(key, result)
        return result

    async def detail(self, namespace: str, name: str) -> PluginDetail:
        key = f"detail:{namespace}.{name}"
        if cached := await self._detail_cache.get(key):
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
        await self._detail_cache.set(key, detail)
        return detail

    async def readme(self, namespace: str, name: str) -> str:
        key = f"readme:{namespace}.{name}"
        if (cached := await self._readme_cache.get(key)) is not None:
            return cached
        detail = await self.detail(namespace, name)
        if not detail.readme_url:
            await self._readme_cache.set(key, "")
            return ""
        url = detail.readme_url
        try:
            resp = await self._http.get(url, timeout=self._s.timeout_s)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            _log.warning("openvsx.readme_http_error", url=url, status=exc.response.status_code)
            raise
        except httpx.HTTPError as exc:
            _log.error("openvsx.readme_unreachable", url=url, error=str(exc))
            raise
        content = resp.text
        await self._readme_cache.set(key, content)
        return content

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
