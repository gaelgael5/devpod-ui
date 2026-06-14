from __future__ import annotations

import asyncio
import contextlib
import json as _json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import httpx
import structlog
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_admin
from ..config.store import _data_root
from ..recipes.models import _RECIPE_ID_RE, RecipeMeta

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
_SH_FNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*\.sh$")


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
        if not _SH_FNAME_RE.fullmatch(fname):
            _log.warning("recipe_sh_invalid_filename", fname=fname)
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


class RecipeImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: str


def _unique_recipe_id(base_id: str, shared_dir: Path) -> str:
    if not (shared_dir / base_id).exists():
        return base_id
    counter = 1
    while (shared_dir / f"{base_id}-{counter}").exists():
        counter += 1
    return f"{base_id}-{counter}"


def _write_recipe(
    shared_dir: Path,
    recipe_id: str,
    version: str,
    description: str,
    install_script: str,
) -> None:
    recipe_path = shared_dir / recipe_id
    tmp = shared_dir / f".tmp-{recipe_id}"
    try:
        tmp.mkdir(parents=True, exist_ok=False)
        meta = RecipeMeta(id=recipe_id, version=version, description=description)
        (tmp / "recipe.meta.yaml").write_text(
            yaml.dump(meta.model_dump(), default_flow_style=False), encoding="utf-8"
        )
        (tmp / "devcontainer-feature.json").write_text(
            _json.dumps({"id": recipe_id, "version": version}, indent=2),
            encoding="utf-8",
        )
        install_sh = tmp / "install.sh"
        install_sh.write_text(install_script, encoding="utf-8")
        install_sh.chmod(0o755)
        tmp.rename(recipe_path)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


@router_admin.post("/recipe-sources/import", status_code=201)
async def import_recipe_from_source(
    body: RecipeImportRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    async with httpx.AsyncClient() as http:
        try:
            content = await _fetch_text(http, body.source_url)
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Cannot fetch recipe: {exc}"
            ) from exc

    headers = _parse_sh_headers(content)
    fname = body.source_url.rsplit("/", 1)[-1]
    base_id = fname[:-3] if fname.endswith(".sh") else fname

    if not _RECIPE_ID_RE.fullmatch(base_id):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid recipe id derived from URL: {base_id!r}",
        )

    data_root = _data_root()
    shared_dir = data_root / "recipes"
    shared_dir.mkdir(parents=True, exist_ok=True)
    recipe_id = await asyncio.to_thread(_unique_recipe_id, base_id, shared_dir)

    await asyncio.to_thread(
        _write_recipe,
        shared_dir,
        recipe_id,
        headers.get("version", "1.0.0"),
        headers.get("description", ""),
        content,
    )
    _log.info("recipe_imported", recipe_id=recipe_id, source=body.source_url, by=user.login)
    return {
        "id": recipe_id,
        "version": headers.get("version", "1.0.0"),
        "description": headers.get("description", ""),
    }
