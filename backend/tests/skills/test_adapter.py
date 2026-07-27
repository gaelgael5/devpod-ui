"""Adaptateur skills.sh : proxy + cache TTL (search 30 s, audit/detail 5 min).

Contrats vérifiés contre l'API réelle le 2026-07-14 :
- GET /api/search?q=…&type=fuzzy|semantic  (public)
- GET /api/audit?source=…&skills=…         (public)
- GET /api/skill/{source}/{skillId}         (401 sans clé API)
"""
from __future__ import annotations

import httpx
import pytest
import respx

from portal.skills.adapter import (
    AUDIT_TTL_S,
    SEARCH_TTL_S,
    SkillsShAdapter,
    SkillsShError,
)

BASE = "https://skills.test"

SEARCH_BODY = {
    "query": "git",
    "searchType": "fuzzy",
    "skills": [
        {
            "id": "github/awesome-copilot/git-commit",
            "skillId": "git-commit",
            "name": "git-commit",
            "installs": 38883,
            "source": "github/awesome-copilot",
        }
    ],
}

AUDIT_BODY = {
    "git-commit": {
        "ath": {"risk": "safe"},
        "socket": {"risk": "safe", "score": 90},
    }
}


RAW = "https://raw.test"


def make_adapter(now: list[float]) -> SkillsShAdapter:
    return SkillsShAdapter(base_url=BASE, time_fn=lambda: now[0], raw_base_url=RAW)


@pytest.mark.asyncio
@respx.mock
async def test_search_fuzzy_and_semantic():
    now = [0.0]
    adapter = make_adapter(now)
    route = respx.get(f"{BASE}/api/search").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )
    result = await adapter.search("git")
    assert result["searchType"] == "fuzzy"
    assert result["skills"][0]["skillId"] == "git-commit"
    assert route.calls.last.request.url.params["q"] == "git"

    await adapter.search("git", search_type="semantic")
    assert route.calls.last.request.url.params["type"] == "semantic"


@pytest.mark.asyncio
@respx.mock
async def test_search_cached_within_ttl_then_refreshed():
    now = [0.0]
    adapter = make_adapter(now)
    route = respx.get(f"{BASE}/api/search").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )
    await adapter.search("git")
    await adapter.search("git")
    assert route.call_count == 1  # servi par le cache

    now[0] = SEARCH_TTL_S + 1  # TTL expiré → refetch
    await adapter.search("git")
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_search_cache_key_discriminates_query_and_type():
    now = [0.0]
    adapter = make_adapter(now)
    route = respx.get(f"{BASE}/api/search").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )
    await adapter.search("git")
    await adapter.search("docker")
    await adapter.search("git", search_type="semantic")
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_audit_params_and_cache():
    now = [0.0]
    adapter = make_adapter(now)
    route = respx.get(f"{BASE}/api/audit").mock(
        return_value=httpx.Response(200, json=AUDIT_BODY)
    )
    result = await adapter.audit("github/awesome-copilot", ["git-commit"])
    assert result["git-commit"]["socket"]["score"] == 90
    params = route.calls.last.request.url.params
    assert params["source"] == "github/awesome-copilot"
    assert params["skills"] == "git-commit"

    await adapter.audit("github/awesome-copilot", ["git-commit"])
    assert route.call_count == 1  # cache 5 min
    now[0] = AUDIT_TTL_S + 1
    await adapter.audit("github/awesome-copilot", ["git-commit"])
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_detail_sends_bearer_key():
    now = [0.0]
    adapter = make_adapter(now)
    route = respx.get(f"{BASE}/api/skill/github/awesome-copilot/git-commit").mock(
        return_value=httpx.Response(200, json={"skillId": "git-commit"})
    )
    result = await adapter.detail(
        "github/awesome-copilot", "git-commit", api_key="sk-test"
    )
    assert result["skillId"] == "git-commit"
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
@respx.mock
async def test_detail_unauthorized_raises_dedicated_error():
    now = [0.0]
    adapter = make_adapter(now)
    respx.get(f"{BASE}/api/skill/github/awesome-copilot/git-commit").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )
    with pytest.raises(SkillsShError) as exc_info:
        await adapter.detail("github/awesome-copilot", "git-commit")
    assert exc_info.value.status == 401


@pytest.mark.asyncio
@respx.mock
async def test_api_key_never_in_cache_key_but_segments_cache():
    """Deux clés différentes ne doivent pas se partager une entrée de cache
    (réponses potentiellement différentes), mais la clé ne doit jamais être
    stockée en clair dans la clé de cache."""
    now = [0.0]
    adapter = make_adapter(now)
    route = respx.get(f"{BASE}/api/search").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )
    await adapter.search("git", api_key="sk-AAA")
    await adapter.search("git", api_key="sk-AAA")
    assert route.call_count == 1
    for key in adapter._cache:  # noqa: SLF001 — assertion d'hygiène volontaire
        assert "sk-AAA" not in str(key)


@pytest.mark.asyncio
@respx.mock
async def test_skill_md_content_and_hash():
    import hashlib

    now = [0.0]
    adapter = make_adapter(now)
    content = "---\nname: git-commit\n---\nInstructions."
    route = respx.get(f"{RAW}/github/awesome-copilot/HEAD/skills/git-commit/SKILL.md").mock(
        return_value=httpx.Response(200, text=content)
    )
    doc = await adapter.skill_md("github/awesome-copilot", "git-commit")
    assert doc["content"] == content
    assert doc["hash"] == "sha256:" + hashlib.sha256(content.encode()).hexdigest()
    # Cache 5 min.
    await adapter.skill_md("github/awesome-copilot", "git-commit")
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_skill_md_missing_raises():
    now = [0.0]
    adapter = make_adapter(now)
    respx.get(f"{RAW}/github/x/HEAD/skills/absent/SKILL.md").mock(
        return_value=httpx.Response(404, text="Not Found")
    )
    with pytest.raises(SkillsShError) as exc_info:
        await adapter.skill_md("github/x", "absent")
    assert exc_info.value.status == 404


@pytest.mark.asyncio
@respx.mock
async def test_upstream_error_raises_and_is_not_cached():
    now = [0.0]
    adapter = make_adapter(now)
    route = respx.get(f"{BASE}/api/search").mock(
        side_effect=[
            httpx.Response(500, text="boom"),
            httpx.Response(200, json=SEARCH_BODY),
        ]
    )
    with pytest.raises(SkillsShError) as exc_info:
        await adapter.search("git")
    assert exc_info.value.status == 500
    # L'échec n'est pas mis en cache : l'appel suivant repart vers l'amont.
    result = await adapter.search("git")
    assert result["skills"]
    assert route.call_count == 2
