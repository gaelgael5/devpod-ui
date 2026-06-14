from __future__ import annotations

import asyncio
import contextlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import httpx
import structlog
import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_admin
from ..config.store import _data_root

_log = structlog.get_logger(__name__)

router_admin = APIRouter(tags=["recipe-sources"])

_DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/gaelgael5/devpod-ui/dev/recipes/toc.txt"
)


class RecipeSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[str]


def _sources_path() -> Path:
    return _data_root() / "recipe-sources.yaml"


def _load_sources() -> list[str]:
    path = _sources_path()
    if not path.exists():
        return [_DEFAULT_SOURCE]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("sources", [_DEFAULT_SOURCE]))


def _save_sources(sources: list[str]) -> None:
    path = _sources_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(yaml.dump({"sources": sources}, default_flow_style=False))
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


@router_admin.get("/recipe-sources")
async def get_recipe_sources(
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    sources = await asyncio.to_thread(_load_sources)
    return {"sources": sources}


_HEADER_RE = re.compile(r"^#\s*(name|description|version)\s*:\s*(.+)$", re.MULTILINE)


def _parse_sh_headers(content: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in _HEADER_RE.finditer(content)}


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=5.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


async def _preview_one_source(
    client: httpx.AsyncClient, toc_url: str
) -> list[dict[str, Any]]:
    base = toc_url.rsplit("/", 1)[0]
    try:
        toc = await _fetch_text(client, toc_url)
    except Exception as exc:
        _log.warning("recipe_source_fetch_failed", url=toc_url, error=str(exc))
        return []
    results: list[dict[str, Any]] = []
    for line in toc.splitlines():
        fname = line.strip()
        if not fname or not fname.endswith(".sh"):
            continue
        sh_url = f"{base}/{fname}"
        try:
            content = await _fetch_text(client, sh_url)
        except Exception as exc:
            _log.warning("recipe_sh_fetch_failed", url=sh_url, error=str(exc))
            continue
        headers = _parse_sh_headers(content)
        recipe_id = fname[:-3]  # strip .sh
        results.append(
            {
                "id": recipe_id,
                "name": headers.get("name", recipe_id),
                "description": headers.get("description", ""),
                "version": headers.get("version", "1.0.0"),
                "source_url": sh_url,
                "install_script": content,
            }
        )
    return results


@router_admin.get("/recipe-sources/preview")
async def preview_recipe_sources(
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    sources = await asyncio.to_thread(_load_sources)
    all_recipes: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as http:
        for src_url in sources:
            recipes = await _preview_one_source(http, src_url)
            all_recipes.extend(recipes)
    return {"recipes": all_recipes}


@router_admin.put("/recipe-sources")
async def put_recipe_sources(
    body: RecipeSourcesPayload,
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    await asyncio.to_thread(_save_sources, body.sources)
    _log.info("recipe_sources_updated", count=len(body.sources), by=user.login)
    return {"sources": body.sources}
