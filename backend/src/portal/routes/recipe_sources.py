from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json as _json
import os
import re
import shutil
import socket as _socket
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

_DEFAULT_SOURCE = "https://raw.githubusercontent.com/gaelgael5/devpod-ui/dev/recipes/toc.txt"


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


@router_admin.get("/recipe-sources")
async def get_recipe_sources(
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    sources = await asyncio.to_thread(_load_sources)
    return {"sources": sources}


# ---------------------------------------------------------------------------
# Parsers toc.txt
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^#\s*(name|description|version)\s*:\s*(.+)$", re.MULTILINE)
_SH_FNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*\.sh$")
# Entrée répertoire : slug valide suivi d'un "/"  (ex. "ansible/")
_DIR_ENTRY_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?/$")


def _parse_sh_headers(content: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in _HEADER_RE.finditer(content)}


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=5.0, follow_redirects=False)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Fetch helpers (format .sh legacy et format répertoire)
# ---------------------------------------------------------------------------


async def _fetch_sh_recipe(
    client: httpx.AsyncClient,
    sh_url: str,
    fname: str,
) -> dict[str, Any] | None:
    """Charge une recette au format legacy : script .sh avec headers commentés."""
    try:
        content = await _fetch_text(client, sh_url)
    except Exception as exc:
        _log.warning("recipe_sh_fetch_failed", url=sh_url, error=str(exc))
        return None
    headers = _parse_sh_headers(content)
    recipe_id = fname[:-3]  # strip .sh
    return {
        "id": recipe_id,
        "name": headers.get("name", recipe_id),
        "description": headers.get("description", ""),
        "version": headers.get("version", "1.0.0"),
        "options": {},
        "installs_after": [],
        "source_url": sh_url,
        "install_script": content,
    }


async def _fetch_dir_recipe(
    client: httpx.AsyncClient,
    base_url: str,
    dirname: str,
) -> dict[str, Any] | None:
    """Charge une recette au format répertoire : recipe.meta.yaml + install.sh."""
    meta_url = f"{base_url}/{dirname}/recipe.meta.yaml"
    sh_url = f"{base_url}/{dirname}/install.sh"

    try:
        meta_text = await _fetch_text(client, meta_url)
        meta = RecipeMeta.model_validate(yaml.safe_load(meta_text))
    except Exception as exc:
        _log.warning("recipe_meta_fetch_failed", url=meta_url, error=str(exc))
        return None

    try:
        install_script = await _fetch_text(client, sh_url)
    except Exception as exc:
        _log.warning("recipe_install_fetch_failed", url=sh_url, error=str(exc))
        return None

    return {
        "id": meta.id,
        "name": meta.id,
        "description": meta.description,
        "version": meta.version,
        "options": {k: v.model_dump() for k, v in meta.options.items()},
        "installs_after": meta.installs_after,
        "source_url": sh_url,
        "install_script": install_script,
    }


async def _preview_one_source(client: httpx.AsyncClient, toc_url: str) -> list[dict[str, Any]]:
    base = toc_url.rsplit("/", 1)[0]
    try:
        toc = await _fetch_text(client, toc_url)
    except Exception as exc:
        _log.warning("recipe_source_fetch_failed", url=toc_url, error=str(exc))
        return []

    results: list[dict[str, Any]] = []
    for line in toc.splitlines():
        entry = line.strip()
        if not entry:
            continue
        if entry.endswith("/"):
            if not _DIR_ENTRY_RE.fullmatch(entry):
                _log.warning("recipe_dir_invalid_entry", entry=entry)
                continue
            result = await _fetch_dir_recipe(client, base, entry.rstrip("/"))
        elif entry.endswith(".sh"):
            if not _SH_FNAME_RE.fullmatch(entry):
                _log.warning("recipe_sh_invalid_filename", fname=entry)
                continue
            result = await _fetch_sh_recipe(client, f"{base}/{entry}", entry)
        else:
            _log.warning("recipe_toc_unknown_entry", entry=entry)
            continue
        if result is not None:
            results.append(result)
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
    for url in body.sources:
        await asyncio.to_thread(_check_ssrf, url)
    await asyncio.to_thread(_save_sources, body.sources)
    _log.info("recipe_sources_updated", count=len(body.sources), by=user.login)
    return {"sources": body.sources}


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class RecipeImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: str


def _unique_recipe_id(base_id: str, shared_dir: Path) -> str:
    if not (shared_dir / base_id).exists():
        return base_id
    counter = 1
    while (shared_dir / f"{base_id}-{counter}").exists():
        counter += 1
        if counter > 100:
            raise ValueError(f"Too many collisions for recipe id {base_id!r}")
    return f"{base_id}-{counter}"


def _write_recipe(
    shared_dir: Path,
    recipe_id: str,
    version: str,
    description: str,
    install_script: str,
    options: dict[str, Any] | None = None,
    installs_after: list[str] | None = None,
) -> None:
    recipe_path = shared_dir / recipe_id
    tmp_str = tempfile.mkdtemp(dir=shared_dir, prefix=f".tmp-{recipe_id}-")
    tmp = Path(tmp_str)
    try:
        meta = RecipeMeta(
            id=recipe_id,
            version=version,
            description=description,
            options=options or {},
            installs_after=installs_after or [],
        )
        (tmp / "recipe.meta.yaml").write_text(
            yaml.dump(meta.model_dump(), default_flow_style=False), encoding="utf-8"
        )
        feature_json: dict[str, Any] = {"id": recipe_id, "version": version}
        if meta.options:
            feature_json["options"] = {k: v.model_dump() for k, v in meta.options.items()}
        (tmp / "devcontainer-feature.json").write_text(
            _json.dumps(feature_json, indent=2), encoding="utf-8"
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
    await asyncio.to_thread(_check_ssrf, body.source_url)

    url_path = Path(urlparse(body.source_url).path)
    fname = url_path.name

    if fname == "install.sh":
        # Format répertoire : fetcher aussi recipe.meta.yaml depuis le même dossier
        dir_base_url = body.source_url.rsplit("/", 1)[0]
        meta_url = f"{dir_base_url}/recipe.meta.yaml"
        async with httpx.AsyncClient() as http:
            try:
                install_script = await _fetch_text(http, body.source_url)
            except Exception as exc:
                raise HTTPException(
                    status_code=502, detail=f"Cannot fetch install.sh: {exc}"
                ) from exc
            try:
                meta_text = await _fetch_text(http, meta_url)
                meta = RecipeMeta.model_validate(yaml.safe_load(meta_text))
            except Exception as exc:
                raise HTTPException(
                    status_code=502, detail=f"Cannot fetch recipe.meta.yaml: {exc}"
                ) from exc
        base_id = meta.id
        version = meta.version
        description = meta.description
        options_dict = {k: v.model_dump() for k, v in meta.options.items()}
        installs_after = meta.installs_after
    else:
        # Format legacy .sh avec headers commentés
        async with httpx.AsyncClient() as http:
            try:
                install_script = await _fetch_text(http, body.source_url)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Cannot fetch recipe: {exc}") from exc
        headers = _parse_sh_headers(install_script)
        base_id = fname[:-3] if fname.endswith(".sh") else fname
        version = headers.get("version", "1.0.0")
        description = headers.get("description", "")
        options_dict = {}
        installs_after = []

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
        version,
        description,
        install_script,
        options_dict,
        installs_after,
    )
    _log.info("recipe_imported", recipe_id=recipe_id, source=body.source_url, by=user.login)
    return {"id": recipe_id, "version": version, "description": description}
