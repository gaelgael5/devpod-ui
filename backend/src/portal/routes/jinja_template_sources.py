"""Routes admin : galerie de templates Jinja2 (sources toc.txt, preview, import)."""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..db.engine import get_conn
from ..db.sources import load_jinja_template_sources, save_jinja_template_sources
from ..messages import db as mdb
from ..messages.models import Jinja2Template
from ._sources_util import split_toc_url
from .recipe_sources import _check_ssrf

_log = structlog.get_logger(__name__)

router_admin = APIRouter(tags=["jinja-template-sources"])

_J2_FNAME_RE = re.compile(r"^[a-zA-Z0-9._-]+\.j2$")
_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_CULTURE_RE = re.compile(r"^[a-z]{2}$")

_DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/ag-flow/ressources/refs/heads/main/jinja/toc.txt"
)


class JinjaSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[str]


class JinjaImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_url: str
    key: str
    culture: str
    overwrite: bool = False


def _parse_toc_line(line: str) -> dict[str, Any] | None:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != 4:
        return None
    filename, key, culture, description = parts
    if not _J2_FNAME_RE.fullmatch(filename):
        return None
    if not _KEY_RE.fullmatch(key):
        return None
    if not _CULTURE_RE.fullmatch(culture):
        return None
    return {"filename": filename, "key": key, "culture": culture, "description": description}


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=5.0, follow_redirects=False)
    resp.raise_for_status()
    return resp.text


async def _preview_one_source(client: httpx.AsyncClient, source: str) -> list[dict[str, Any]]:
    toc_url, dir_base = split_toc_url(source)
    try:
        toc = await _fetch_text(client, toc_url)
    except Exception as exc:
        _log.warning("jinja_source_fetch_failed", url=toc_url, error=str(exc))
        return []
    results: list[dict[str, Any]] = []
    for raw_line in toc.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = _parse_toc_line(line)
        if parsed is None:
            _log.warning("jinja_toc_invalid_line", line=line)
            continue
        results.append(
            {
                **parsed,
                "source_url": f"{dir_base}/{parsed['filename']}",
                "source_base": dir_base,
            }
        )
    return results


@router_admin.get("/jinja-template-sources")
async def get_jinja_template_sources(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    sources = await load_jinja_template_sources(conn)
    return {"sources": sources}


@router_admin.put("/jinja-template-sources")
async def put_jinja_template_sources(
    body: JinjaSourcesPayload,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    for url in body.sources:
        if not url.startswith("https://"):
            raise HTTPException(status_code=422, detail=f"URL must be HTTPS: {url!r}")
        await asyncio.to_thread(_check_ssrf, url)
    await save_jinja_template_sources(body.sources, conn)
    _log.info("jinja_sources_updated", count=len(body.sources), by=user.login)
    return {"sources": body.sources}


@router_admin.get("/jinja-template-sources/preview")
async def preview_jinja_template_sources(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    sources = await load_jinja_template_sources(conn)
    all_templates: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as http:
        for src_url in sources:
            try:
                await asyncio.to_thread(_check_ssrf, src_url)
            except HTTPException as exc:
                _log.warning("jinja_source_ssrf_blocked", url=src_url, detail=exc.detail)
                continue
            all_templates.extend(await _preview_one_source(http, src_url))
    return {"templates": all_templates}


@router_admin.post("/jinja-template-sources/import", status_code=200)
async def import_jinja_template(
    body: JinjaImportRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> Jinja2Template:
    if not _KEY_RE.fullmatch(body.key):
        raise HTTPException(status_code=422, detail=f"Invalid key: {body.key!r}")
    if not _CULTURE_RE.fullmatch(body.culture):
        raise HTTPException(status_code=422, detail=f"Invalid culture: {body.culture!r}")
    filename = body.source_url.rsplit("/", 1)[-1]
    if not _J2_FNAME_RE.fullmatch(filename):
        raise HTTPException(status_code=422, detail=f"Invalid filename: {filename!r}")

    await asyncio.to_thread(_check_ssrf, body.source_url)
    async with httpx.AsyncClient() as http:
        try:
            content = await _fetch_text(http, body.source_url)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Cannot fetch template: {exc}") from exc

    existing = await mdb.get_template(conn, body.key, body.culture)
    if existing is not None and not body.overwrite:
        raise HTTPException(status_code=409, detail="template_exists")

    tpl = Jinja2Template(key=body.key, culture=body.culture, body=content)
    await mdb.upsert_template(conn, tpl)
    _log.info(
        "jinja_template_imported",
        key=body.key,
        culture=body.culture,
        overwrite=body.overwrite,
        by=user.login,
    )
    return tpl
