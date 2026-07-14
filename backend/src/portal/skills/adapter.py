"""Adaptateur skills.sh — proxy + cache des lectures (search, audit, detail).

Service ISOLÉ : la gateway et les routes ne parlent jamais directement à
l'API tierce (découplage voulu par l'epic skills). Contrats vérifiés contre
l'API réelle le 2026-07-14 :

- ``GET /api/search?q=…&type=fuzzy|semantic`` (public) →
  ``{query, searchType, skills: [{id, skillId, name, installs, source}]}``
- ``GET /api/audit?source=…&skills=a,b`` (public) → ``{<skillId>: {ath, socket,
  snyk, zeroleaks…}}``
- ``GET /api/skill/{source}/{skillId}`` (detail) → 401 sans clé API.

La clé API est OPTIONNELLE (relève la limite de débit / debloque le detail) et
ne sert JAMAIS à l'installation — `npx skills add` reste sans clé. Schéma
d'auth supposé `Authorization: Bearer` (à confirmer avec une clé réelle ; le
401 public ne documente pas le schéma).

Cache TTL en mémoire par process : search 30 s, audit/detail 5 min (bornes de
la fiche backlog). Les échecs ne sont jamais mis en cache. La clé API n'entre
jamais en clair dans les clés de cache (empreinte SHA-256 tronquée).
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx
import structlog

from ..settings import get_settings

_log = structlog.get_logger(__name__)

SEARCH_TTL_S = 30.0
AUDIT_TTL_S = 300.0
DETAIL_TTL_S = 300.0
_TIMEOUT_S = 10.0

# Clé de cache : (endpoint, paramètres…, empreinte de clé API). Valeur : (expiration, payload).
_CacheKey = tuple[str, ...]


class SkillsShError(Exception):
    """Erreur amont skills.sh (statut HTTP non-2xx ou réseau)."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def _key_fingerprint(api_key: str | None) -> str:
    """Empreinte non réversible de la clé API pour segmenter le cache sans
    jamais stocker la clé en clair."""
    if not api_key:
        return "-"
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]


class SkillsShAdapter:
    """Proxy + cache TTL des lectures skills.sh. Une instance par process."""

    def __init__(
        self,
        base_url: str | None = None,
        time_fn: Any = time.monotonic,
        raw_base_url: str | None = None,
    ) -> None:
        self._base_url = (base_url or get_settings().skills_sh_base_url).rstrip("/")
        self._raw_base_url = (
            raw_base_url or get_settings().skills_raw_base_url
        ).rstrip("/")
        self._time = time_fn
        self._cache: dict[_CacheKey, tuple[float, Any]] = {}

    # ── Lectures publiques ────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        search_type: str = "fuzzy",
        api_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {"q": query}
        if search_type != "fuzzy":
            params["type"] = search_type
        cache_key = ("search", query, search_type, _key_fingerprint(api_key))
        return await self._get_cached(
            "/api/search", params, cache_key, SEARCH_TTL_S, api_key
        )

    async def audit(
        self,
        source: str,
        skill_ids: list[str],
        api_key: str | None = None,
    ) -> dict[str, Any]:
        params = {"source": source, "skills": ",".join(skill_ids)}
        cache_key = ("audit", source, params["skills"], _key_fingerprint(api_key))
        return await self._get_cached(
            "/api/audit", params, cache_key, AUDIT_TTL_S, api_key
        )

    async def detail(
        self,
        source: str,
        skill_id: str,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        path = f"/api/skill/{source}/{skill_id}"
        cache_key = ("detail", source, skill_id, _key_fingerprint(api_key))
        return await self._get_cached(path, {}, cache_key, DETAIL_TTL_S, api_key)

    async def skill_md(self, source: str, skill_id: str) -> dict[str, str]:
        """Contenu canonique du SKILL.md + son SHA-256 : `{"content", "hash"}`.

        Récupéré depuis GitHub raw (`{source}/HEAD/skills/{skill_id}/SKILL.md`),
        PUBLIC et sans clé — c'est la même source que `npx skills add`, donc le
        même contenu que hashera la vérification post-install. Hôte FIXE
        (raw.githubusercontent.com) + segments validés par les routes : pas de
        SSRF possible. Cache 5 min.
        """
        cache_key = ("skill_md", source, skill_id, "-")
        now = self._time()
        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return dict(cached[1])
        url = (
            f"{self._raw_base_url}/{source}/HEAD/skills/{skill_id}/SKILL.md"
        )
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=_TIMEOUT_S, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise SkillsShError(f"skill content unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise SkillsShError(
                f"SKILL.md introuvable pour {source}/{skill_id} "
                f"(HTTP {resp.status_code})",
                status=resp.status_code,
            )
        content = resp.text
        payload = {
            "content": content,
            "hash": "sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        }
        self._cache[cache_key] = (now + DETAIL_TTL_S, payload)
        return payload

    # ── Transport + cache ─────────────────────────────────────────────────────

    async def _get_cached(
        self,
        path: str,
        params: dict[str, str],
        cache_key: _CacheKey,
        ttl_s: float,
        api_key: str | None,
    ) -> dict[str, Any]:
        now = self._time()
        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return dict(cached[1])

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            async with httpx.AsyncClient(base_url=self._base_url) as client:
                resp = await client.get(
                    path, params=params, headers=headers, timeout=_TIMEOUT_S
                )
        except httpx.HTTPError as exc:
            raise SkillsShError(f"skills.sh unreachable: {exc}") from exc

        if resp.status_code != 200:
            # Jamais de mise en cache d'un échec ; le corps d'erreur amont est
            # court ({"error": …}) et sans secret — propagé pour le diagnostic.
            raise SkillsShError(
                f"skills.sh {path} -> {resp.status_code}: {resp.text[:200]}",
                status=resp.status_code,
            )

        payload: dict[str, Any] = resp.json()
        self._cache[cache_key] = (now + ttl_s, payload)
        return payload


_adapter: SkillsShAdapter | None = None


def get_skills_adapter() -> SkillsShAdapter:
    """Singleton par process (cache partagé entre routes et surface MCP)."""
    global _adapter
    if _adapter is None:
        _adapter = SkillsShAdapter()
    return _adapter
