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

from ..auth.rbac import UserInfo, require_user
from ..config.models import ProfileRef, SourceSpec, WorkspaceSpec
from ..config.store import _data_root, load_global, safe_user_path
from ..devpod.env import UnknownHostError
from ..devpod.git import run_git_ls_remote
from ..devpod.service import DevPodService
from ..profiles.models import Profile
from ..profiles.repository import ProfileError, ProfileRepository
from ..recipes.models import _RECIPE_ID_RE as _RECIPE_ID_PATTERN
from ..recipes.models import RecipeMeta, SecretRef
from ..recipes.registry import RecipeRegistry

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


_service: DevPodService | None = None
_recipe_registry: RecipeRegistry | None = None


def _get_recipe_registry() -> RecipeRegistry:
    global _recipe_registry
    if _recipe_registry is None:
        _recipe_registry = RecipeRegistry(builtin_dir=None, shared_dir=_data_root() / "recipes")
    return _recipe_registry


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

    exposure: ExposureService | None = None
    if global_cfg.caddy.admin_api:
        data_root = _data_root()
        verify_uri = f"{global_cfg.server.external_url}/auth/caddy/verify"
        dev_mode = global_cfg.server.dev_mode
        caddy = CaddyClient(
            admin_api=global_cfg.caddy.admin_api,
            http_client=httpx.AsyncClient(),
            verify_uri=verify_uri,
            require_auth=not dev_mode,
        )
        registry = PortRegistry(data_root)
        exposure = ExposureService(
            caddy=caddy,
            registry=registry,
            data_root=data_root,
            base_domain=global_cfg.server.base_domain,
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


def _resolve_feature_secrets(login: str, secret_refs: list[SecretRef]) -> dict[str, str]:
    """Résout les secrets de recettes. Appelée via asyncio.to_thread."""
    from ..config.store import load_user
    from ..secrets.factory import create_backend
    from ..secrets.resolver import Scope, resolve
    from ..secrets.types import Secret

    user_cfg = load_user(login)
    global_cfg = load_global()
    user_secrets_path = safe_user_path(login, "secrets.yaml")
    backend = create_backend(
        backend_type=global_cfg.secrets.backend,
        url=global_cfg.secrets.harpocrate.url,
        api_key=global_cfg.secrets.harpocrate.api_key,
        base_path=global_cfg.secrets.harpocrate.base_path,
        user_secrets_path=user_secrets_path,
    )
    scope = Scope(kind="user", secret_ns=user_cfg.secret_ns, login=login)
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
        shared = await asyncio.to_thread(reg.load_shared)
        personal_dir = safe_user_path(user.login, "recipes")
        personal = await asyncio.to_thread(reg.load_dir, personal_dir)
        available = {**shared, **personal}

        try:
            resolved_recipes = reg.resolve_order(req.recipes, available)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        all_refs: list[SecretRef] = [
            ref for recipe in resolved_recipes for ref in recipe.requires_secrets
        ]
        if all_refs:
            try:
                feature_env = await asyncio.to_thread(
                    _resolve_feature_secrets, user.login, all_refs
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
            repo = ProfileRepository(_data_root())
            profile_obj = await asyncio.to_thread(
                repo.get, req.profile.scope, req.profile.slug, user.login
            )
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
) -> list[dict[str, Any]]:
    """Liste les recettes start attachées à un workspace."""
    _validate_name(name)

    from ..config.store import load_user

    user_cfg = await asyncio.to_thread(load_user, user.login)
    ws_spec = next((ws for ws in user_cfg.workspaces if ws.name == name), None)
    if ws_spec is None:
        raise HTTPException(status_code=404, detail=f"Workspace {name!r} not found")
    if not ws_spec.start_recipes:
        return []

    reg = _get_recipe_registry()
    shared = await asyncio.to_thread(reg.load_shared)
    personal_dir = safe_user_path(user.login, "recipes")
    personal = await asyncio.to_thread(reg.load_dir, personal_dir)
    available = {**shared, **personal}

    return [
        available[rid].model_dump()
        for rid in ws_spec.start_recipes
        if rid in available and available[rid].type == "start"
    ]


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
