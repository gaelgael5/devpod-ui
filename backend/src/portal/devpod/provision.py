"""Orchestration de provisioning réutilisable (route REST + MCP workspace_create)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..config.models import WorkspaceSpec
from ..db.profiles import AsyncProfileRepository
from ..profiles.models import Profile
from ..profiles.repository import ProfileError
from ..recipes.models import RecipeMeta
from .service import DevPodService

_log = structlog.get_logger(__name__)


class SecretResolutionError(Exception):
    """Échec de résolution d'un secret — message rédigé, jamais la valeur ni l'erreur brute."""


def _get_service() -> DevPodService:
    from ..routes.workspace_ops import _get_service as _svc

    return _svc()


@dataclass
class ProvisionParams:
    name: str
    source: str
    branch: str = ""
    git_credential: str = ""
    host: str = ""
    recipes: list[str] = field(default_factory=list)
    extra_sources: list[Any] = field(default_factory=list)
    profile: Any = None
    recipe_volumes: list[str] = field(default_factory=list)
    generate_ssh_key: bool = False
    request_host: str = ""


async def _resolve_recipes_and_secrets(
    login: str, recipe_ids: list[str], conn: AsyncConnection
) -> tuple[list[RecipeMeta], dict[str, str]]:
    """Résout les recettes et leurs secrets. Déplacé de workspace_ops.workspace_up."""
    if not recipe_ids:
        return [], {}

    from ..db.recipes import load_recipes_as_dict
    from ..routes.workspace_ops import (
        _available_with_bundled_fallback,
        _get_recipe_registry,
        _resolve_feature_secrets,
    )

    reg = _get_recipe_registry()
    available = _available_with_bundled_fallback(await load_recipes_as_dict(login, conn))
    expanded = reg.expand_with_deps(recipe_ids, available)
    resolved = reg.resolve_order(expanded, available)

    all_refs = [ref for r in resolved for ref in r.requires_secrets]
    env: dict[str, str] = {}
    if all_refs:
        from ..config.store import load_user as _lu

        cfg = await _lu(login)
        try:
            env = await asyncio.to_thread(_resolve_feature_secrets, login, cfg.secret_ns, all_refs)
        except Exception as exc:
            _log.warning("feature_secret_resolution_failed", login=login, error=type(exc).__name__)
            raise SecretResolutionError(f"Secret resolution failed: {type(exc).__name__}") from exc

    return resolved, env


async def _load_profile(login: str, profile_ref: Any) -> Profile | None:
    """Résout un profil. Dégradation gracieuse si absent."""
    if profile_ref is None:
        return None
    try:
        return await AsyncProfileRepository().get(profile_ref.scope, profile_ref.slug, login)
    except ProfileError:
        _log.warning(
            "workspace.profile_missing",
            scope=getattr(profile_ref, "scope", ""),
            slug=getattr(profile_ref, "slug", ""),
        )
        return None


async def provision_workspace(
    login: str, params: ProvisionParams, conn: AsyncConnection
) -> str:
    """Provisionne un workspace : résolution recettes/secrets/profil + svc.up.

    Retourne le ws_id produit par DevPodService.up.
    """
    resolved, feature_env = await _resolve_recipes_and_secrets(login, params.recipes, conn)
    profile_obj = await _load_profile(login, params.profile)
    ws = WorkspaceSpec(
        name=params.name,
        source=params.source,
        branch=params.branch,
        git_credential=params.git_credential,
        host=params.host,
        recipes=params.recipes,
        extra_sources=params.extra_sources,
        profile=params.profile,
        recipe_volumes=params.recipe_volumes,
    )
    return await _get_service().up(
        login=login,
        ws_spec=ws,
        recipes=resolved or None,
        feature_env=feature_env or None,
        generate_ssh_key=params.generate_ssh_key,
        request_host=params.request_host,
        profile=profile_obj,
    )
