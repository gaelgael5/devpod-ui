# backend/src/portal/routes/recipes.py
from __future__ import annotations

import shutil
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..auth.rbac import UserInfo, require_admin, require_user
from ..config.store import _data_root, safe_user_path
from ..recipes.models import _RECIPE_ID_RE
from ..recipes.registry import RecipeRegistry

_log = structlog.get_logger(__name__)

router_public = APIRouter(tags=["recipes"])
router_me = APIRouter(tags=["recipes-me"])
router_admin = APIRouter(tags=["recipes-admin"])


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
    registry = RecipeRegistry(shared_dir=data_root / "recipes")
    shared = registry.load_shared()
    personal_dir = safe_user_path(user.login, "recipes")
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
    personal_dir = safe_user_path(user.login, "recipes")
    recipe_path = personal_dir / recipe_id
    if not recipe_path.is_relative_to(personal_dir):
        raise HTTPException(status_code=422, detail="Path traversal detected")
    if not recipe_path.exists():
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id!r} not found")
    shutil.rmtree(recipe_path)
    _log.info("personal_recipe_deleted", login=user.login, recipe_id=recipe_id)
    return {"deleted": recipe_id}


@router_admin.get("/recipes")
async def admin_list_recipes(
    user: UserInfo = Depends(require_admin),
) -> list[dict[str, Any]]:
    """Liste les recettes partagées (admin only)."""
    data_root = _data_root()
    registry = RecipeRegistry(shared_dir=data_root / "recipes")
    shared = registry.load_shared()
    return [m.model_dump() for m in shared.values()]


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
    shutil.rmtree(recipe_path)
    _log.info("shared_recipe_deleted", login=user.login, recipe_id=recipe_id)
    return {"deleted": recipe_id}
