# backend/src/portal/routes/recipes.py
from __future__ import annotations

import asyncio
import contextlib
import json as _json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import structlog
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator

from ..auth.rbac import UserInfo, require_admin, require_user
from ..config.store import _builtin_recipes_dir, _data_root, safe_user_path
from ..recipes.models import _RECIPE_ID_RE, RecipeMeta
from ..recipes.registry import RecipeRegistry

_log = structlog.get_logger(__name__)

router_public = APIRouter(tags=["recipes"])
router_me = APIRouter(tags=["recipes-me"])
router_admin = APIRouter(tags=["recipes-admin"])

_DEFAULT_INSTALL_SH = "#!/usr/bin/env bash\nset -e\necho 'Installing...'\n"


class RecipeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str = "1.0.0"
    description: str = ""
    install_script: str = _DEFAULT_INSTALL_SH

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not _RECIPE_ID_RE.fullmatch(v):
            raise ValueError(
                f"id {v!r} must match ^[a-z0-9]([a-z0-9-]{{0,38}}[a-z0-9])?$"
            )
        return v


class RecipeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    description: str
    install_script: str


def _validate_recipe_id(recipe_id: str) -> None:
    if not _RECIPE_ID_RE.fullmatch(recipe_id):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid recipe id {recipe_id!r}",
        )


@router_public.get("/recipes")
async def list_recipes(user: UserInfo = Depends(require_user)) -> list[dict[str, Any]]:
    """Liste les recettes partagées + personnelles visibles par l'utilisateur."""
    data_root = _data_root()
    shared_dir = data_root / "recipes"
    personal_dir = safe_user_path(user.login, "recipes")
    registry = RecipeRegistry(builtin_dir=_builtin_recipes_dir(), shared_dir=shared_dir)
    shared = registry.load_shared()
    personal = registry.load_dir(personal_dir)
    available = {**shared, **personal}
    return [m.model_dump() for m in available.values()]


@router_me.delete("/recipes/{recipe_id}")
async def delete_personal_recipe(
    recipe_id: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, Any]:
    """Supprime une recette personnelle."""
    _validate_recipe_id(recipe_id)
    try:
        personal_dir = safe_user_path(user.login, "recipes")
        recipe_path = personal_dir / recipe_id
        if not recipe_path.is_relative_to(personal_dir):
            raise HTTPException(status_code=422, detail="Path traversal detected")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid recipe path") from exc
    if not recipe_path.exists():
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id!r} not found")
    await asyncio.to_thread(shutil.rmtree, recipe_path)
    _log.info("personal_recipe_deleted", login=user.login, recipe_id=recipe_id)
    return {"deleted": recipe_id}


@router_admin.get("/recipes")
async def admin_list_recipes(
    user: UserInfo = Depends(require_admin),
) -> list[dict[str, Any]]:
    """Liste les recettes partagées (importées / créées) avec install_script (admin only).

    Les recettes builtin (baked-in) ne sont pas listées ici : elles ne peuvent
    pas être supprimées ni modifiées via l'API admin.
    """
    data_root = _data_root()
    shared_recipes_dir = data_root / "recipes"
    shared_metas = RecipeRegistry(builtin_dir=None, shared_dir=shared_recipes_dir).load_shared()
    results: list[dict[str, Any]] = []
    for meta in shared_metas.values():
        entry = meta.model_dump()
        install_sh = shared_recipes_dir / meta.id / "install.sh"
        entry["install_script"] = (
            install_sh.read_text(encoding="utf-8") if install_sh.exists() else ""
        )
        results.append(entry)
    return results


@router_admin.post("/recipes", status_code=201)
async def admin_create_shared_recipe(
    body: RecipeCreateRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    """Crée une recette partagée avec son install.sh."""
    data_root = _data_root()
    shared_recipes_dir = data_root / "recipes"
    recipe_path = shared_recipes_dir / body.id
    if recipe_path.exists():
        raise HTTPException(status_code=409, detail=f"Recipe {body.id!r} already exists")

    meta = RecipeMeta(id=body.id, version=body.version, description=body.description)

    def _write() -> None:
        tmp = shared_recipes_dir / f".tmp-{body.id}"
        try:
            tmp.mkdir(parents=True, exist_ok=False)
            (tmp / "recipe.meta.yaml").write_text(
                yaml.dump(meta.model_dump(), default_flow_style=False), encoding="utf-8"
            )
            (tmp / "devcontainer-feature.json").write_text(
                _json.dumps({"id": body.id, "version": body.version}, indent=2),
                encoding="utf-8",
            )
            install_sh = tmp / "install.sh"
            install_sh.write_text(body.install_script, encoding="utf-8")
            install_sh.chmod(0o755)
            tmp.rename(recipe_path)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    await asyncio.to_thread(_write)
    _log.info("shared_recipe_created", recipe_id=body.id, by=user.login)
    return meta.model_dump()


@router_admin.put("/recipes/{recipe_id}")
async def admin_update_shared_recipe(
    recipe_id: str,
    body: RecipeUpdateRequest,
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    """Met à jour version, description et install.sh d'une recette partagée."""
    _validate_recipe_id(recipe_id)
    data_root = _data_root()
    shared_recipes_dir = data_root / "recipes"
    recipe_path = shared_recipes_dir / recipe_id
    if not recipe_path.is_relative_to(shared_recipes_dir):
        raise HTTPException(status_code=422, detail="Path traversal detected")
    if not recipe_path.exists():
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id!r} not found")

    meta = RecipeMeta(id=recipe_id, version=body.version, description=body.description)

    def _update() -> None:
        def _write_atomic(path: Path, content: str) -> None:
            fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_name, path)
            except Exception:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
                raise

        _write_atomic(
            recipe_path / "recipe.meta.yaml",
            yaml.dump(meta.model_dump(), default_flow_style=False),
        )
        _write_atomic(
            recipe_path / "devcontainer-feature.json",
            _json.dumps({"id": recipe_id, "version": body.version}, indent=2),
        )
        _write_atomic(recipe_path / "install.sh", body.install_script)
        (recipe_path / "install.sh").chmod(0o755)

    await asyncio.to_thread(_update)
    _log.info("shared_recipe_updated", recipe_id=recipe_id, by=user.login)
    entry = meta.model_dump()
    entry["install_script"] = body.install_script
    return entry


@router_admin.delete("/recipes/{recipe_id}")
async def admin_delete_shared_recipe(
    recipe_id: str,
    user: UserInfo = Depends(require_admin),
) -> dict[str, Any]:
    """Supprime une recette partagée admin (ne supprime pas les builtin)."""
    _validate_recipe_id(recipe_id)
    data_root = _data_root()
    shared_recipes_dir = data_root / "recipes"
    recipe_path = shared_recipes_dir / recipe_id
    if not recipe_path.is_relative_to(shared_recipes_dir):
        raise HTTPException(status_code=422, detail="Path traversal detected")
    if not recipe_path.exists():
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id!r} not found")
    await asyncio.to_thread(shutil.rmtree, recipe_path)
    _log.info("shared_recipe_deleted", login=user.login, recipe_id=recipe_id)
    return {"deleted": recipe_id}
