"""Routes admin : sources de la galerie compose (toc.txt) + import."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket as _socket
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..compose import db as cdb
from ..compose.models import ComposeTemplate, validate_slug
from ..db.engine import get_conn
from ..db.sources import load_compose_sources, save_compose_sources

_log = structlog.get_logger(__name__)

router_admin = APIRouter(tags=["compose-sources"])

# ─── Validation slug répertoire (même contrainte que recipe_sources) ──────────

_DIR_ENTRY_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?/$")

# ─── Anti-SSRF (identique recipe_sources) ────────────────────────────────────


def _check_ssrf(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=422, detail=f"URL scheme must be http or https: {url!r}")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise HTTPException(status_code=422, detail="URL has no hostname")
    try:
        infos = _socket.getaddrinfo(host, None)
    except _socket.gaierror as exc:
        raise HTTPException(
            status_code=422, detail=f"Cannot resolve hostname '{host}': {exc}"
        ) from exc
    for _fam, _type, _proto, _canon, sa in infos:
        try:
            ip = ipaddress.ip_address(sa[0])
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_private
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise HTTPException(
                status_code=422,
                detail=f"URL resolves to a blocked internal address: {ip}",
            )


# ─── Fetch helpers ────────────────────────────────────────────────────────────


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    await asyncio.to_thread(_check_ssrf, url)
    resp = await client.get(url, timeout=5.0, follow_redirects=False)
    resp.raise_for_status()
    return resp.text


# ─── Parseur toc.txt compose ─────────────────────────────────────────────────


async def _fetch_compose_entry(
    client: httpx.AsyncClient,
    base_url: str,
    dirname: str,
) -> dict[str, Any] | None:
    meta_url = f"{base_url}/{dirname}/meta.yaml"
    compose_url = f"{base_url}/{dirname}/compose.yml"

    try:
        meta_text = await _fetch_text(client, meta_url)
        meta = yaml.safe_load(meta_text)
    except Exception as exc:
        _log.warning("compose_meta_fetch_failed", url=meta_url, error=str(exc))
        return None

    if not isinstance(meta, dict):
        _log.warning("compose_meta_invalid", url=meta_url)
        return None

    return {
        "id": meta.get("id", dirname),
        "name": meta.get("name", dirname),
        "description": meta.get("description", ""),
        "version": meta.get("version", "1.0.0"),
        "tags": list(meta.get("tags", [])),
        "image": meta.get("image", ""),
        "source_url": compose_url,
    }


async def _preview_one_source(
    client: httpx.AsyncClient, toc_url: str
) -> list[dict[str, Any]]:
    base = toc_url.rsplit("/", 1)[0]
    try:
        toc = await _fetch_text(client, toc_url)
    except Exception as exc:
        _log.warning("compose_source_fetch_failed", url=toc_url, error=str(exc))
        return []

    results: list[dict[str, Any]] = []
    for line in toc.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if not entry.endswith("/"):
            _log.warning("compose_toc_unknown_entry", entry=entry)
            continue
        if not _DIR_ENTRY_RE.fullmatch(entry):
            _log.warning("compose_toc_invalid_entry", entry=entry)
            continue
        result = await _fetch_compose_entry(client, base, entry.rstrip("/"))
        if result is not None:
            results.append(result)
    return results


# ─── Routes ──────────────────────────────────────────────────────────────────


class ComposeSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[str]


@router_admin.get("/compose-sources")
async def get_compose_sources(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    sources = await load_compose_sources(conn)
    return {"sources": sources}


@router_admin.put("/compose-sources")
async def put_compose_sources(
    body: ComposeSourcesPayload,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    for url in body.sources:
        await asyncio.to_thread(_check_ssrf, url)
    await save_compose_sources(body.sources, conn)
    _log.info("compose_sources_updated", count=len(body.sources), by=user.login)
    return {"sources": body.sources}


@router_admin.get("/compose-sources/preview")
async def preview_compose_sources(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    sources = await load_compose_sources(conn)
    all_entries: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as http:
        for src_url in sources:
            entries = await _preview_one_source(http, src_url)
            all_entries.extend(entries)
    return {"templates": all_entries}


# ─── Import ───────────────────────────────────────────────────────────────────


class ComposeImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: str


@router_admin.post("/compose-sources/import", status_code=201)
async def import_compose_from_source(
    body: ComposeImportRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    await asyncio.to_thread(_check_ssrf, body.source_url)

    compose_url = body.source_url
    meta_url = compose_url.rsplit("/", 1)[0] + "/meta.yaml"

    try:
        async with httpx.AsyncClient() as http:
            meta_text = await _fetch_text(http, meta_url)
            compose_content = await _fetch_text(http, compose_url)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    meta = yaml.safe_load(meta_text)
    if not isinstance(meta, dict):
        raise HTTPException(status_code=422, detail="meta.yaml invalide")

    template_id = str(meta.get("id", ""))
    try:
        validate_slug(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    tpl = ComposeTemplate(
        id=template_id,
        name=str(meta.get("name", template_id)),
        description=str(meta.get("description", "")),
        version=str(meta.get("version", "1.0.0")),
        tags=list(meta.get("tags", [])),
        compose_content=compose_content,
        parameters=[],
        source=compose_url,
    )

    existing = await cdb.get_template(conn, template_id)
    if existing is None:
        await cdb.create_template(conn, tpl)
        _log.info("compose_template_imported", id=template_id, source=compose_url, by=user.login)
    else:
        await cdb.update_template(conn, tpl)
        _log.info("compose_template_updated", id=template_id, source=compose_url, by=user.login)

    return {"id": template_id}
