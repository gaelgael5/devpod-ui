from __future__ import annotations

import asyncio
import ipaddress
import json as _json
import re
import shutil
import socket as _socket
import tempfile
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
import structlog
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..config.store import _data_root
from ..db.engine import get_conn
from ..db.sources import load_recipe_sources, save_recipe_sources
from ..recipes.models import _RECIPE_ID_RE, RecipeMeta

_log = structlog.get_logger(__name__)

router_admin = APIRouter(tags=["recipe-sources"])


def _normalize_recipe_yaml(data: Any) -> Any:
    """Renomme le champ legacy 'category' en 'type' avant validation du modèle."""
    if isinstance(data, dict) and "category" in data and "type" not in data:
        data = dict(data)
        data["type"] = data.pop("category")
    return data

_DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/ag-flow/ressources/refs/heads/main/recipes/toc.txt"
)


class RecipeSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[str]


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
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    sources = await load_recipe_sources(conn)
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
    await asyncio.to_thread(_check_ssrf, url)
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
        "type": headers.get("type", "install"),
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
        meta = RecipeMeta.model_validate(_normalize_recipe_yaml(yaml.safe_load(meta_text)))
    except Exception as exc:
        _log.warning("recipe_meta_fetch_failed", url=meta_url, error=str(exc))
        return None

    try:
        install_script = await _fetch_text(client, sh_url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            install_script = ""  # optionnel pour les recettes type=initialize
        else:
            _log.warning("recipe_install_fetch_failed", url=sh_url, error=str(exc))
            return None
    except Exception as exc:
        _log.warning("recipe_install_fetch_failed", url=sh_url, error=str(exc))
        return None

    return {
        "id": meta.id,
        "key": meta.key,
        "name": meta.id,
        "description": meta.description,
        "version": meta.version,
        "type": meta.type,
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
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    sources = await load_recipe_sources(conn)
    all_recipes: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as http:
        for src_url in sources:
            recipes = await _preview_one_source(http, src_url)
            all_recipes.extend(recipes)

    # Recettes bundlées (livrées avec le produit), importables localement.
    seen = {r["id"] for r in all_recipes}
    for r in await asyncio.to_thread(_bundled_recipes):
        if r["id"] not in seen:
            all_recipes.append(r)
    return {"recipes": all_recipes}


@router_admin.put("/recipe-sources")
async def put_recipe_sources(
    body: RecipeSourcesPayload,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    for url in body.sources:
        await asyncio.to_thread(_check_ssrf, url)
    await save_recipe_sources(body.sources, conn)
    _log.info("recipe_sources_updated", count=len(body.sources), by=user.login)
    return {"sources": body.sources}


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class RecipeImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: str


async def _purge_orphan_recipe_dirs(
    base_id: str, shared_dir: Path, conn: AsyncConnection
) -> None:
    """Supprime les dossiers de recettes présents sur le disque mais absents de la DB.

    Scanne base_id, base_id-1, base_id-2, ... et supprime les orphelins afin que
    l'import suivant puisse réutiliser l'ID canonique sans générer de suffixe.
    """
    from ..db.recipes import get_recipe_db

    counter = 0
    while True:
        dir_id = base_id if counter == 0 else f"{base_id}-{counter}"
        cand = shared_dir / dir_id
        if not cand.exists():
            if counter == 0:
                return  # rien à nettoyer
            break
        in_db = await get_recipe_db(dir_id, "shared", None, conn) is not None
        if not in_db:
            await asyncio.to_thread(shutil.rmtree, cand, True)
            _log.info("orphan_recipe_dir_purged", path=str(cand))
        counter += 1
        if counter > 100:
            break


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
    recipe_type: Literal["install", "start", "initialize"] = "install",
) -> None:
    recipe_path = shared_dir / recipe_id
    tmp_str = tempfile.mkdtemp(dir=shared_dir, prefix=f".tmp-{recipe_id}-")
    tmp = Path(tmp_str)
    try:
        meta = RecipeMeta(
            id=recipe_id,
            version=version,
            description=description,
            type=recipe_type,
            options=options or {},
            installs_after=installs_after or [],
        )
        (tmp / "recipe.meta.yaml").write_text(
            yaml.dump(meta.model_dump(by_alias=True), default_flow_style=False),
            encoding="utf-8",
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


async def _find_recipe_by_key(
    key: str,
    sources: list[str],
    http: httpx.AsyncClient,
) -> dict[str, Any] | None:
    """Parcourt les sources configurées pour trouver la recette dont key == UUID donné."""
    for toc_url in sources:
        for r in await _preview_one_source(http, toc_url):
            if r.get("key") == key:
                return r
    return None


async def _import_single_recipe(
    source_url: str,
    shared_dir: Path,
    http: httpx.AsyncClient,
    conn: AsyncConnection,
) -> tuple[str, RecipeMeta]:
    """Télécharge et écrit sur disque une recette. Retourne (recipe_id, meta)."""
    from ..db.recipes import upsert_recipe_db

    url_path = Path(urlparse(source_url).path)
    fname = url_path.name

    recipe_type: Literal["install", "start", "initialize"] = "install"
    if fname == "install.sh":
        dir_base_url = source_url.rsplit("/", 1)[0]
        meta_url = f"{dir_base_url}/recipe.meta.yaml"
        install_script = await _fetch_text(http, source_url)
        meta_text = await _fetch_text(http, meta_url)
        meta = RecipeMeta.model_validate(_normalize_recipe_yaml(yaml.safe_load(meta_text)))
        recipe_type = meta.type
        options_dict = {k: v.model_dump() for k, v in meta.options.items()}
        installs_after = meta.installs_after
        base_id = meta.id
        version = meta.version
        description = meta.description
    else:
        install_script = await _fetch_text(http, source_url)
        headers = _parse_sh_headers(install_script)
        base_id = fname[:-3] if fname.endswith(".sh") else fname
        version = headers.get("version", "1.0.0")
        description = headers.get("description", "")
        raw_type = headers.get("type", "install")
        if raw_type == "start":
            recipe_type = "start"
        elif raw_type == "initialize":
            recipe_type = "initialize"
        # sinon recipe_type reste "install" (valeur par défaut)
        options_dict = {}
        installs_after = []
        meta = RecipeMeta(
            id=base_id, version=version, description=description, type=recipe_type
        )

    if not _RECIPE_ID_RE.fullmatch(base_id):
        raise ValueError(f"Invalid recipe id: {base_id!r}")

    await _purge_orphan_recipe_dirs(base_id, shared_dir, conn)
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
        recipe_type,
    )
    final_meta = RecipeMeta(
        id=recipe_id,
        key=meta.key,
        version=version,
        description=description,
        type=recipe_type,
        installs_after=installs_after,
    )
    await upsert_recipe_db(final_meta, "shared", None, conn)
    return recipe_id, final_meta


async def _import_with_deps(
    source_url: str,
    shared_dir: Path,
    http: httpx.AsyncClient,
    sources: list[str],
    conn: AsyncConnection,
    seen_keys: set[str],
) -> list[str]:
    """Importe une recette et ses dépendances (installs_after) récursivement.

    Retourne la liste des recipe_id importés (dépendances en premier).
    """
    from ..db.recipes import recipe_key_exists

    imported: list[str] = []

    url_path = Path(urlparse(source_url).path)
    if url_path.name == "install.sh":
        dir_base_url = source_url.rsplit("/", 1)[0]
        meta_url = f"{dir_base_url}/recipe.meta.yaml"
        try:
            meta_text = await _fetch_text(http, meta_url)
            meta = RecipeMeta.model_validate(_normalize_recipe_yaml(yaml.safe_load(meta_text)))
        except Exception as exc:
            _log.warning("dep_meta_fetch_failed", url=meta_url, error=str(exc))
            meta = None
    else:
        meta = None

    if meta is not None and meta.key in seen_keys:
        return imported
    if meta is not None:
        seen_keys.add(meta.key)
        if await recipe_key_exists(meta.key, conn):
            return imported

        for dep_key in meta.installs_after:
            if dep_key in seen_keys:
                continue
            if await recipe_key_exists(dep_key, conn):
                seen_keys.add(dep_key)
                continue
            dep = await _find_recipe_by_key(dep_key, sources, http)
            if dep is None:
                _log.warning("dep_recipe_not_found", key=dep_key)
                continue
            dep_imported = await _import_with_deps(
                dep["source_url"], shared_dir, http, sources, conn, seen_keys
            )
            imported.extend(dep_imported)

    recipe_id, _ = await _import_single_recipe(source_url, shared_dir, http, conn)
    imported.append(recipe_id)
    return imported


@router_admin.post("/recipe-sources/import", status_code=201)
async def import_recipe_from_source(
    body: RecipeImportRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    await asyncio.to_thread(_check_ssrf, body.source_url)

    data_root = _data_root()
    shared_dir = data_root / "recipes"
    shared_dir.mkdir(parents=True, exist_ok=True)

    configured_sources = await load_recipe_sources(conn)

    try:
        async with httpx.AsyncClient() as http:
            imported_ids = await _import_with_deps(
                body.source_url,
                shared_dir,
                http,
                configured_sources,
                conn,
                seen_keys=set(),
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    main_id = imported_ids[-1] if imported_ids else ""
    _log.info(
        "recipe_imported",
        recipe_id=main_id,
        deps=imported_ids[:-1],
        source=body.source_url,
        by=user.login,
    )
    return {"id": main_id, "imported": imported_ids}


# ─── Recettes bundlées (locales) dans la galerie d'import ──────────────────────


def _bundled_bases() -> list[Path]:
    """Répertoires des recettes livrées avec le produit (repo en dev, image en prod)."""
    repo = Path(__file__).resolve().parents[4] / "recipes"
    return [p for p in (repo, Path("/app/recipes")) if p.exists()]


def _bundled_recipe_dir(recipe_id: str) -> Path | None:
    for base in _bundled_bases():
        cand = base / recipe_id
        if (cand / "recipe.meta.yaml").exists() and cand.is_relative_to(base):
            return cand
    return None


def _bundled_recipes() -> list[dict[str, Any]]:
    """Liste les recettes bundlées au format galerie (source_url = local:<id>)."""
    out: dict[str, dict[str, Any]] = {}
    for base in _bundled_bases():
        for entry in sorted(base.iterdir()):
            meta_file = entry / "recipe.meta.yaml"
            if not entry.is_dir() or not meta_file.exists():
                continue
            try:
                raw = yaml.safe_load(meta_file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict) and "category" in raw and "type" not in raw:
                    raw["type"] = raw.pop("category")
                meta = RecipeMeta.model_validate(raw)
            except Exception as exc:
                _log.warning("bundled_recipe_invalid", path=str(meta_file), error=str(exc))
                continue
            if meta.id in out:
                continue
            install_sh = entry / "install.sh"
            out[meta.id] = {
                "id": meta.id,
                "key": meta.key,
                "name": meta.id,
                "description": meta.description,
                "version": meta.version,
                "type": meta.type,
                "options": {k: v.model_dump() for k, v in meta.options.items()},
                "installs_after": meta.installs_after,
                "source_url": f"local:{meta.id}",
                "install_script": (
                    install_sh.read_text(encoding="utf-8") if install_sh.exists() else ""
                ),
            }
    return list(out.values())


class LocalImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str


@router_admin.post("/recipes/import-local", status_code=201)
async def import_local_recipe(
    body: LocalImportRequest,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Importe une recette bundlée (et ses dépendances bundlées) → /data/recipes + DB."""
    if not _RECIPE_ID_RE.fullmatch(body.recipe_id):
        raise HTTPException(status_code=422, detail=f"Invalid recipe id {body.recipe_id!r}")

    from ..recipes.registry import RecipeRegistry
    from ..recipes.sync import sync_recipes_to_db

    reg = RecipeRegistry()
    available: dict[str, RecipeMeta] = {}
    for base in _bundled_bases():
        for rid, meta in reg.load_dir(base).items():
            available.setdefault(rid, meta)
    if body.recipe_id not in available:
        raise HTTPException(
            status_code=404, detail=f"Bundled recipe {body.recipe_id!r} not found"
        )

    ids = reg.expand_with_deps([body.recipe_id], available)
    shared_dir = _data_root() / "recipes"
    shared_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for rid in ids:
        src = _bundled_recipe_dir(rid)
        if src is None:
            continue
        shutil.copytree(src, shared_dir / rid, dirs_exist_ok=True)
        copied.append(rid)

    await sync_recipes_to_db(shared_dir, conn)
    _log.info("local_recipe_imported", recipe_id=body.recipe_id, imported=copied, by=user.login)
    return {"id": body.recipe_id, "imported": copied}
