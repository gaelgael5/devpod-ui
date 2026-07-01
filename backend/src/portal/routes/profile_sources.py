from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import structlog
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..db.engine import get_conn
from ..db.profiles import AsyncProfileRepository
from ..db.sources import load_profile_sources, save_profile_sources
from ..profiles.models import ProfileBody
from ..profiles.repository import slugify
from .recipe_sources import _check_ssrf

_log = structlog.get_logger(__name__)

router_admin = APIRouter(tags=["profile-sources"])

_YAML_FNAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.yaml$")

_DEFAULT_SOURCE = "https://raw.githubusercontent.com/ag-flow/ressources/main/profiles/"


class ProfileSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[str]


class ProfileImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_url: str


def _parse_toc_line(line: str) -> dict[str, Any] | None:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != 4:
        return None
    filename, name, description, ext_count_str = parts
    if not _YAML_FNAME_RE.fullmatch(filename):
        return None
    try:
        extension_count = int(ext_count_str)
    except ValueError:
        extension_count = 0
    return {
        "filename": filename,
        "name": name,
        "description": description,
        "extension_count": extension_count,
    }


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=5.0, follow_redirects=False)
    resp.raise_for_status()
    return resp.text


async def _preview_one_source(client: httpx.AsyncClient, base_url: str) -> list[dict[str, Any]]:
    toc_url = base_url.rstrip("/") + "/toc.txt"
    try:
        toc = await _fetch_text(client, toc_url)
    except Exception as exc:
        _log.warning("profile_source_fetch_failed", url=toc_url, error=str(exc))
        return []
    results: list[dict[str, Any]] = []
    for raw_line in toc.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = _parse_toc_line(line)
        if parsed is None:
            _log.warning("profile_toc_invalid_line", line=line)
            continue
        results.append(
            {
                **parsed,
                "source_url": f"{base_url.rstrip('/')}/{parsed['filename']}",
                "source_base": base_url,
            }
        )
    return results


@router_admin.get("/profile-sources")
async def get_profile_sources(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    sources = await load_profile_sources(conn)
    return {"sources": sources}


@router_admin.put("/profile-sources")
async def put_profile_sources(
    body: ProfileSourcesPayload,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    for url in body.sources:
        if not url.startswith("https://"):
            raise HTTPException(status_code=422, detail=f"URL must be HTTPS: {url!r}")
        await asyncio.to_thread(_check_ssrf, url)
    await save_profile_sources(body.sources, conn)
    _log.info("profile_sources_updated", count=len(body.sources), by=user.login)
    return {"sources": body.sources}


@router_admin.get("/profile-sources/preview")
async def preview_profile_sources(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    sources = await load_profile_sources(conn)
    all_profiles: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as http:
        for src_url in sources:
            try:
                await asyncio.to_thread(_check_ssrf, src_url)
            except HTTPException as exc:
                _log.warning(
                    "profile_source_ssrf_blocked",
                    url=src_url,
                    detail=exc.detail,
                )
                continue
            profiles = await _preview_one_source(http, src_url)
            all_profiles.extend(profiles)
    return {"profiles": all_profiles}


@router_admin.post("/profile-sources/import", status_code=201)
async def import_profile_from_source(
    body: ProfileImportRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    await asyncio.to_thread(_check_ssrf, body.source_url)

    async with httpx.AsyncClient() as http:
        try:
            content = await _fetch_text(http, body.source_url)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Cannot fetch profile: {exc}") from exc

    try:
        raw = yaml.safe_load(content) or {}
        profile_body = ProfileBody(**raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid profile YAML: {exc}") from exc

    expected_slug = slugify(profile_body.name)

    repo = AsyncProfileRepository()
    profile = await repo.create_shared(profile_body)

    if profile.slug != expected_slug:
        # create_shared a auto-renommé → conflit de slug
        await repo.delete_shared(profile.slug)
        raise HTTPException(status_code=409, detail="profile_slug_conflict")

    await repo.set_gallery_source(profile.slug, body.source_url)
    _log.info("profile_imported", slug=profile.slug, source=body.source_url, by=user.login)
    return profile.model_dump()
