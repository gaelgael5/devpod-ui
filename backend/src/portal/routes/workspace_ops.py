from __future__ import annotations

import asyncio
import os
import re
import shlex
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..config.models import ProfileRef, SourceSpec, WorkspaceSpec
from ..config.store import _data_root, load_global, safe_user_path
from ..db.engine import get_conn
from ..db.profiles import AsyncProfileRepository
from ..db.recipes import load_recipes_as_dict
from ..devpod.env import HostNotReadyError, UnknownHostError
from ..devpod.git import run_git_ls_remote
from ..devpod.service import DevPodService
from ..profiles.models import Profile
from ..profiles.repository import ProfileError
from ..recipes.models import _RECIPE_ID_RE as _RECIPE_ID_PATTERN
from ..recipes.models import RecipeMeta, SecretRef
from ..recipes.registry import DependencyNotFoundError, RecipeRegistry

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["workspace-ops"])

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")


def _validate_name(name: str) -> None:
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid workspace name {name!r}: must match ^[a-z0-9][a-z0-9-]{{0,30}}[a-z0-9]$"
            ),
        )


class UpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = ""
    branch: str = ""
    git_credential: str = ""
    host: str = ""
    recipes: list[str] = Field(default_factory=list)
    extra_sources: list[SourceSpec] = Field(default_factory=list)
    generate_ssh_key: bool = False
    profile: ProfileRef | None = None
    recipe_volumes: list[str] = Field(default_factory=list)


_service: DevPodService | None = None
_recipe_registry: RecipeRegistry | None = None


def _get_recipe_registry() -> RecipeRegistry:
    global _recipe_registry
    if _recipe_registry is None:
        _recipe_registry = RecipeRegistry(builtin_dir=None, shared_dir=_data_root() / "recipes")
    return _recipe_registry


def _available_with_bundled_fallback(db_available: dict[str, RecipeMeta]) -> dict[str, RecipeMeta]:
    """Enrichit le dict DB avec les recettes lues directement depuis le filesystem.

    Ordre de priorité (du plus faible au plus fort) :
      /app/recipes/ (bundlées image) < /data/recipes/ (volume) < DB
    Lecture directe YAML (utf-8-sig pour gérer le BOM Windows) — évite que
    _load_meta avale silencieusement les erreurs et cache un problème de parsing.
    """
    from pathlib import Path

    import yaml as _yaml

    # Chemins de recherche, du MOINS prioritaire au PLUS prioritaire.
    # Le dernier dict écrase les précédents → /app/recipes/ gagne toujours sur
    # /data/recipes/ (qui peut contenir d'anciens fichiers sans champ key).
    #   <repo>/recipes/   — fallback développement local (hors Docker)
    #   /data/recipes/    — volume partagé (recettes admin, peut être périmé)
    #   /app/recipes/     — recettes bundlées dans l'image Docker (source canonique)
    _repo_recipes = Path(__file__).resolve().parents[4] / "recipes"
    fs: dict[str, RecipeMeta] = {}
    for base in (_repo_recipes, _data_root() / "recipes", Path("/app/recipes")):
        if not base.exists():
            _log.warning("recipe_fallback_dir_absent", path=str(base))
            continue
        for recipe_dir in sorted(base.iterdir()):
            if not recipe_dir.is_dir():
                continue
            meta_file = recipe_dir / "recipe.meta.yaml"
            if not meta_file.exists():
                continue
            try:
                # utf-8-sig supprime le BOM UTF-8 éventuel (fichiers créés sur Windows)
                raw: object = _yaml.safe_load(meta_file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict) and "category" in raw and "type" not in raw:
                    raw = dict(raw)
                    raw["type"] = raw.pop("category")
                meta = RecipeMeta.model_validate(raw)
                fs[meta.id] = meta
            except Exception as exc:
                _log.warning(
                    "recipe_fallback_skip",
                    path=str(meta_file),
                    error=str(exc),
                    exc_type=type(exc).__name__,
                )

    _log.debug(
        "recipe_fallback_loaded",
        count=len(fs),
        ids=sorted(fs),
        db_ids=sorted(db_available),
    )
    if not fs:
        return db_available
    # FS a priorité sur DB pour garantir que les GUIDs (key) des recettes bundlées
    # sont toujours corrects — la DB peut avoir un key périmé si la recette a été
    # insérée avant l'introduction du champ key dans recipe.meta.yaml.
    # Les recettes uniquement en DB (créées par l'utilisateur) sont préservées.
    return {**db_available, **fs}


def _get_service() -> DevPodService:
    global _service
    if _service is None:
        _service = _build_service()
    return _service


def _build_service() -> DevPodService:
    import httpx

    from ..exposure import ExposureService
    from ..exposure.caddy import CaddyClient
    from ..exposure.ports import PortRegistry

    global_cfg = load_global()
    # shlex.split with posix=False preserves Windows backslash paths intact.
    # On POSIX systems posix=True (default) would also work for single-token paths
    # like "/usr/local/bin/devpod"; using posix=False is safe for both platforms.
    devpod_bin = shlex.split(global_cfg.devpod.binary, posix=(os.name != "nt"))

    dev_mode = global_cfg.server.dev_mode
    registry = PortRegistry()
    caddy: CaddyClient | None = None
    if global_cfg.caddy.admin_api:
        verify_uri = f"{global_cfg.server.external_url}/auth/caddy/verify"
        caddy = CaddyClient(
            admin_api=global_cfg.caddy.admin_api,
            http_client=httpx.AsyncClient(),
            verify_uri=verify_uri,
            require_auth=not dev_mode,
        )
    exposure = ExposureService(
        registry=registry,
        base_domain=global_cfg.server.base_domain,
        caddy=caddy,
        url_scheme="http" if dev_mode else "https",
        dev_mode=dev_mode,
        external_url=global_cfg.server.external_url,
        workspace_host=global_cfg.server.workspace_host,
    )

    return DevPodService(global_cfg=global_cfg, devpod_bin=devpod_bin, exposure=exposure)


def _reset_service() -> None:
    """Réinitialise le singleton du service (tests uniquement)."""
    global _service, _recipe_registry
    _service = None
    _recipe_registry = None


def _resolve_feature_secrets(
    login: str, secret_ns: str, secret_refs: list[SecretRef]
) -> dict[str, str]:
    """Résout les secrets de recettes. Appelée via asyncio.to_thread."""
    from ..secrets.factory import create_backend
    from ..secrets.resolver import Scope, resolve
    from ..secrets.types import Secret

    global_cfg = load_global()
    user_secrets_path = safe_user_path(login, "secrets.yaml")
    backend = create_backend(
        backend_type=global_cfg.secrets.backend,
        url=global_cfg.secrets.harpocrate.url,
        api_key=global_cfg.secrets.harpocrate.api_key,
        base_path=global_cfg.secrets.harpocrate.base_path,
        user_secrets_path=user_secrets_path,
    )
    scope = Scope(kind="user", secret_ns=secret_ns, login=login)
    result: dict[str, str] = {}
    for ref in secret_refs:
        val = resolve(ref.path, scope, backend)
        result[ref.env] = val.reveal() if isinstance(val, Secret) else str(val)
    return result


@router.post("/workspaces/{name}/up", status_code=202)
async def workspace_up(
    name: str,
    req: UpRequest,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    _validate_name(name)

    # Validation des recipe IDs (avant tout accès disque)
    for rid in req.recipes:
        if not _RECIPE_ID_PATTERN.fullmatch(rid):
            raise HTTPException(status_code=422, detail=f"Invalid recipe id {rid!r}")

    # Validation des sources supplémentaires
    for idx, src in enumerate(req.extra_sources):
        if not src.url:
            raise HTTPException(
                status_code=422, detail=f"extra_sources[{idx}].url must not be empty"
            )
        if src.url.startswith("-"):
            raise HTTPException(
                status_code=422,
                detail=f"extra_sources[{idx}].url must not start with '-'",
            )

    # Résolution des recettes et de leurs secrets
    resolved_recipes: list[RecipeMeta] = []
    feature_env: dict[str, str] = {}

    if req.recipes:
        reg = _get_recipe_registry()
        available = _available_with_bundled_fallback(await load_recipes_as_dict(user.login, conn))

        try:
            expanded = reg.expand_with_deps(req.recipes, available)
            resolved_recipes = reg.resolve_order(expanded, available)
        except DependencyNotFoundError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        all_refs: list[SecretRef] = [
            ref for recipe in resolved_recipes for ref in recipe.requires_secrets
        ]
        if all_refs:
            from ..config.store import load_user

            user_cfg_for_secrets = await load_user(user.login)
            try:
                feature_env = await asyncio.to_thread(
                    _resolve_feature_secrets, user.login, user_cfg_for_secrets.secret_ns, all_refs
                )
            except Exception as exc:
                _log.warning(
                    "feature_secret_resolution_failed",
                    login=user.login,
                    error=type(exc).__name__,
                )
                raise HTTPException(
                    status_code=422,
                    detail=f"Secret resolution failed: {type(exc).__name__}",
                ) from exc

    # Résolution du profil (dégradation gracieuse si absent)
    profile_obj: Profile | None = None
    if req.profile is not None:
        try:
            repo = AsyncProfileRepository()
            profile_obj = await repo.get(req.profile.scope, req.profile.slug, user.login)
        except ProfileError:
            _log.warning(
                "workspace.profile_missing",
                scope=req.profile.scope,
                slug=req.profile.slug,
            )

    try:
        ws = WorkspaceSpec(
            name=name,
            source=req.source,
            branch=req.branch,
            git_credential=req.git_credential,
            host=req.host,
            recipes=req.recipes,
            extra_sources=req.extra_sources,
            profile=req.profile,
            recipe_volumes=req.recipe_volumes,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Pre-flight git : vérifie l'accès au dépôt avant de lancer devpod up
    if req.source:
        returncode, _, stderr = await run_git_ls_remote(req.source, req.git_credential, user.login)
        if returncode != 0:
            err = stderr.decode(errors="replace").strip() if stderr else ""
            _log.warning(
                "workspace_git_preflight_failed",
                login=user.login,
                source=req.source,
                returncode=returncode,
                err=err[:300],
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Dépôt git inaccessible — vérifiez l'URL et les credentials ({req.source})"
                ),
            )

    # Synchronise le spec en DB — le host (et autres champs) peut différer de la valeur
    # stockée lors de la création initiale (ex. 409 ignoré, reprovisioning avec autre host).
    from ..config.store import load_user
    from ..config.store import save_user as _save_user

    _up_fields = {
        "source": req.source,
        "branch": req.branch,
        "git_credential": req.git_credential,
        "host": req.host,
        "recipes": req.recipes,
        "extra_sources": req.extra_sources,
        "profile": req.profile,
        "recipe_volumes": req.recipe_volumes,
    }
    _user_cfg = await load_user(user.login)
    for _i, _existing in enumerate(_user_cfg.workspaces):
        if _existing.name == name:
            _updated = _existing.model_copy(update=_up_fields)
            if _updated != _existing:
                _user_cfg.workspaces[_i] = _updated
                await _save_user(user.login, _user_cfg)
                _log.info("workspace_spec_synced", login=user.login, name=name)
            break

    svc = _get_service()
    request_host = request.headers.get("x-forwarded-host") or request.url.hostname or ""
    try:
        ws_id = await svc.up(
            login=user.login,
            ws_spec=ws,
            recipes=resolved_recipes or None,
            feature_env=feature_env or None,
            generate_ssh_key=req.generate_ssh_key,
            request_host=request_host,
            profile=profile_obj,
        )
    except HostNotReadyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnknownHostError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _log.info("workspace_up_requested", login=user.login, ws_id=ws_id)
    return {"ws_id": ws_id, "status": "provisioning"}


@router.post("/workspaces/{name}/stop")
async def workspace_stop(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, Any]:
    _validate_name(name)
    ws_id = f"{user.login}-{name}"
    svc = _get_service()
    await svc.stop(login=user.login, ws_id=ws_id)
    return {"ws_id": ws_id, "status": "stopped"}


@router.post("/workspaces/{name}/delete")
async def workspace_delete(
    name: str,
    user: UserInfo = Depends(require_user),
    shelve: bool = True,
) -> dict[str, Any]:
    _validate_name(name)
    ws_id = f"{user.login}-{name}"
    svc = _get_service()
    result = await svc.delete(login=user.login, ws_id=ws_id, shelve=shelve)
    return {"ws_id": ws_id, **result}


@router.post("/workspaces/{name}/recreate", status_code=202)
async def workspace_recreate(
    name: str,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Supprime le workspace DevPod et le recrée avec les paramètres stockés."""
    _validate_name(name)

    from ..config.store import load_user

    cfg = await load_user(user.login)
    ws = next((w for w in cfg.workspaces if w.name == name), None)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"Workspace {name!r} introuvable")

    ws_id = f"{user.login}-{name}"
    svc = _get_service()

    # Supprimer le workspace DevPod sans shelve — recréation immédiate
    await svc.delete(login=user.login, ws_id=ws_id, shelve=False)

    # Résolution des recettes
    resolved_recipes: list[RecipeMeta] = []
    feature_env: dict[str, str] = {}
    if ws.recipes:
        reg = _get_recipe_registry()
        available = _available_with_bundled_fallback(await load_recipes_as_dict(user.login, conn))
        try:
            expanded = reg.expand_with_deps(ws.recipes, available)
            resolved_recipes = reg.resolve_order(expanded, available)
        except DependencyNotFoundError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        all_refs: list[SecretRef] = [ref for r in resolved_recipes for ref in r.requires_secrets]
        if all_refs:
            try:
                feature_env = await asyncio.to_thread(
                    _resolve_feature_secrets, user.login, cfg.secret_ns, all_refs
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Secret resolution failed: {type(exc).__name__}",
                ) from exc

    # Résolution du profil
    profile_obj: Profile | None = None
    if ws.profile is not None:
        try:
            repo = AsyncProfileRepository()
            profile_obj = await repo.get(ws.profile.scope, ws.profile.slug, user.login)
        except ProfileError:
            _log.warning("workspace_recreate_profile_missing", login=user.login, name=name)

    request_host = request.headers.get("x-forwarded-host") or request.url.hostname or ""
    try:
        ws_id = await svc.up(
            login=user.login,
            ws_spec=ws,
            recipes=resolved_recipes or None,
            feature_env=feature_env or None,
            generate_ssh_key=ws.ssh_key,
            request_host=request_host,
            profile=profile_obj,
        )
    except HostNotReadyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnknownHostError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _log.info("workspace_recreate_requested", login=user.login, ws_id=ws_id)
    return {"ws_id": ws_id, "status": "provisioning"}


@router.get("/workspaces/{name}/status")
async def workspace_status(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, Any]:
    _validate_name(name)
    ws_id = f"{user.login}-{name}"
    svc = _get_service()
    return await svc.status(login=user.login, ws_id=ws_id)


@router.get("/workspaces/{name}/ssh-key")
async def get_workspace_ssh_key(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, str]:
    _validate_name(name)
    pub_path = safe_user_path(user.login, "keys", "workspaces", name) / "id_ed25519.pub"
    if not pub_path.exists():
        raise HTTPException(
            status_code=404,
            detail="SSH key not generated for this workspace",
        )
    return {"public_key": pub_path.read_text(encoding="utf-8").strip()}


@router.get("/workspaces/{name}/start-recipes")
async def get_workspace_start_recipes(
    name: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Liste les recettes start attachées à un workspace."""
    _validate_name(name)

    from ..config.store import load_user

    user_cfg = await load_user(user.login)
    ws_spec = next((ws for ws in user_cfg.workspaces if ws.name == name), None)
    if ws_spec is None:
        raise HTTPException(status_code=404, detail=f"Workspace {name!r} not found")
    if not ws_spec.start_recipes:
        return []

    available = await load_recipes_as_dict(user.login, conn, type_filter="start")

    return [available[rid].model_dump() for rid in ws_spec.start_recipes if rid in available]


@router.get("/workspaces/{name}/initializers")
async def get_workspace_initializers(
    name: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Liste les actions initialize attachées à un workspace."""
    _validate_name(name)

    from ..config.store import load_user

    user_cfg = await load_user(user.login)
    ws_spec = next((ws for ws in user_cfg.workspaces if ws.name == name), None)
    if ws_spec is None:
        raise HTTPException(status_code=404, detail=f"Workspace {name!r} not found")
    if not ws_spec.init_recipes:
        return []

    available = await load_recipes_as_dict(user.login, conn, type_filter="initialize")
    out: list[dict[str, Any]] = []
    for rid in ws_spec.init_recipes:
        meta = available.get(rid)
        if meta is not None:
            out.append({"id": meta.id, "description": meta.description, "version": meta.version})
    return out


class RunInitializerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied: bool
    already_applied: bool
    log: str


@router.post("/workspaces/{name}/initializers/{recipe_id}/run")
async def run_workspace_initializer(
    name: str,
    recipe_id: str,
    force: bool = False,
    user: UserInfo = Depends(require_user),
) -> RunInitializerResponse:
    """Exécute une action initialize dans le conteneur du workspace."""
    _validate_name(name)
    if not _RECIPE_ID_PATTERN.fullmatch(recipe_id):
        raise HTTPException(status_code=422, detail=f"Invalid recipe id {recipe_id!r}")

    from ..config.store import load_user
    from ..recipes.initializers import (
        InitializerError,
        locate_recipe_dir,
        run_initializer,
    )

    user_cfg = await load_user(user.login)
    ws_spec = next((ws for ws in user_cfg.workspaces if ws.name == name), None)
    if ws_spec is None:
        raise HTTPException(status_code=404, detail=f"Workspace {name!r} not found")
    if recipe_id not in ws_spec.init_recipes:
        raise HTTPException(
            status_code=404,
            detail=f"{recipe_id!r} is not an initializer of workspace {name!r}",
        )

    ws_id = f"{user.login}-{name}"
    status = await _get_service().status(login=user.login, ws_id=ws_id)
    if status.get("status") != "running":
        raise HTTPException(
            status_code=409, detail="Workspace must be running to run an initializer"
        )

    recipe_dir = locate_recipe_dir(user.login, recipe_id)
    if recipe_dir is None:
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id!r} not found")
    meta = RecipeMeta.from_yaml(recipe_dir / "recipe.meta.yaml")
    if meta.type != "initialize":
        raise HTTPException(
            status_code=422, detail=f"Recipe {recipe_id!r} is not of type initialize"
        )

    try:
        result = await run_initializer(user.login, name, meta, recipe_dir, force=force)
    except InitializerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RunInitializerResponse(**result)


@router.get("/workspaces/{name}/logs", response_class=PlainTextResponse)
async def get_workspace_logs(
    name: str,
    user: UserInfo = Depends(require_user),
) -> str:
    _validate_name(name)
    ws_id = f"{user.login}-{name}"
    logs_root = _data_root() / "logs"
    log_file = logs_root / user.login / f"{ws_id}.log"
    if not log_file.is_relative_to(logs_root):
        raise HTTPException(status_code=422, detail="Invalid log path")
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    _log.info("workspace_logs_fetched", login=user.login, ws_id=ws_id)
    content = await asyncio.to_thread(log_file.read_text, encoding="utf-8", errors="replace")
    return content[-100_000:]
