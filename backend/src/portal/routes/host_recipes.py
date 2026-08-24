"""Application des recettes de host depuis le portail (ticket 76a74588).

Exécution de code à distance avec les droits d'administration de la machine —
plus permissif que le cas workspace, où le conteneur bornait les dégâts. D'où :

- la recette est désignée par son **identifiant de catalogue**, jamais par un
  chemin ni une commande transitant dans la requête ;
- la compatibilité de famille est vérifiée AVANT toute connexion ;
- l'action est réservée aux administrateurs.

L'application est **asynchrone** : une recette de host pèse parfois 20 Go, bien
au-delà de tout timeout HTTP. La requête rend la main sur un identifiant
d'opération, jamais sur le résultat.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..config.models import HostConfig
from ..config.store import load_global
from ..db.engine import get_conn
from ..db.recipes import load_recipes_as_dict
from ..devpod.host_exec import run_host_command
from ..events.bus import emit_event
from ..mcp.devpod_tools.operations import launch_operation
from ..recipes.host_apply import (
    PROBE_TIMEOUT_S,
    HostApplyError,
    apply_recipe_to_host,
    build_state_probe,
    parse_state,
    resolve_options,
)
from ..recipes.initializers import locate_recipe_dir
from ..recipes.models import _RECIPE_ID_RE, RecipeMeta


class ApplyRecipeRequest(BaseModel):
    """Parametres de la recette. Valides contre sa declaration cote service."""

    model_config = ConfigDict(extra="forbid")

    options: dict[str, str] = Field(default_factory=dict)


router = APIRouter(tags=["host-recipes"])
log = structlog.get_logger(__name__)


def _load_host(name: str) -> HostConfig | None:
    return next((h for h in load_global().hosts if h.name == name), None)


async def _load_host_recipes(login: str, conn: AsyncConnection) -> dict[str, RecipeMeta]:
    return await load_recipes_as_dict(login, conn)


def _read_install_script(recipe_id: str) -> str | None:
    """Contenu de `install.sh`, ou None si la recette n'en porte pas.

    Lu depuis le catalogue synchronisé sur disque, jamais depuis la requête.
    """
    # `locate_recipe_dir` applique déjà la garde anti-traversal via safe_user_path.
    directory = locate_recipe_dir("", recipe_id)
    if directory is None:
        return None
    script: Path = directory / "install.sh"
    return script.read_text(encoding="utf-8") if script.is_file() else None


async def _probe_state(host: HostConfig) -> dict[str, Any]:
    """Ce que la MACHINE dit porter. Injoignable → état inconnu, pas une erreur.

    Le catalogue reste consultable même quand la machine est éteinte : refuser
    la page entière pour ça priverait l'administrateur de toute information.
    """
    try:
        rc, out, _err = await run_host_command(host, build_state_probe(), timeout=PROBE_TIMEOUT_S)
    except Exception:
        log.warning("host_recipes_state_probe_failed", host=host.name, exc_info=True)
        return {}
    if rc != 0:
        return {}
    return {
        rid: {"version": s.version, "applied_at": s.applied_at}
        for rid, s in parse_state(out).items()
    }


async def _launch(**kwargs: Any) -> str:
    return await launch_operation(**kwargs)


def _require_applicable(meta: RecipeMeta | None, recipe_id: str, host: HostConfig) -> RecipeMeta:
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Recette {recipe_id!r} introuvable")
    if meta.scope != "host":
        detail = f"Recette {recipe_id!r} de portée workspace, non applicable à une machine"
        raise HTTPException(status_code=422, detail=detail)
    if not meta.applies_to_host(host.usage):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Recette {recipe_id!r} non applicable à la famille {host.usage!r} — "
                f"familles déclarées : {', '.join(meta.host_usages)}"
            ),
        )
    return meta


@router.get("/hosts/{name}/recipes")
async def list_host_recipes(
    name: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Recettes applicables à cette machine, et celles qu'elle porte déjà."""
    host = _load_host(name)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} introuvable")

    catalogue = await _load_host_recipes(user.login, conn)
    available = [
        {"id": m.id, "version": m.version, "description": m.description}
        for m in catalogue.values()
        if m.applies_to_host(host.usage)
    ]
    return {"installed": await _probe_state(host), "available": available}


@router.post("/hosts/{name}/recipes/{recipe_id}", status_code=202)
async def apply_host_recipe(
    name: str,
    recipe_id: str,
    body: ApplyRecipeRequest | None = None,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    """Lance l'application et rend la main sur un identifiant d'opération."""
    if not _RECIPE_ID_RE.fullmatch(recipe_id):
        raise HTTPException(
            status_code=422, detail=f"Identifiant de recette invalide: {recipe_id!r}"
        )

    host = _load_host(name)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} introuvable")

    catalogue = await _load_host_recipes(user.login, conn)
    meta = _require_applicable(catalogue.get(recipe_id), recipe_id, host)

    try:
        resolve_options(meta, body.options if body else {})
    except HostApplyError as exc:
        # Refuse tout de suite : une option invalide n'a pas a etre decouverte
        # dans le journal d'une operation lancee pour rien.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    script = _read_install_script(recipe_id)
    if script is None:
        raise HTTPException(
            status_code=422, detail=f"Recette {recipe_id!r} sans install.sh — rien à appliquer"
        )

    async def work() -> dict[str, Any]:
        async def run(command: str, *, timeout: float) -> tuple[int, str, str]:
            return await run_host_command(host, command, timeout=timeout)

        try:
            result = await apply_recipe_to_host(
                meta,
                host_usage=host.usage,
                script=script,
                run=run,
                options=body.options if body else {},
            )
        except HostApplyError as exc:
            # Le message porte déjà la cause exploitable (précondition, code retour).
            raise RuntimeError(str(exc)) from exc
        await emit_event(
            "host_recipe.applied",
            actor=user.login,
            subject={
                "host": host.name,
                "recipe": meta.id,
                "version": result.version,
                "changed": result.changed,
            },
        )
        return {"changed": result.changed, "version": result.version}

    operation_id = await _launch(
        kind="host_recipe_apply", workspace=host.name, owner_login=user.login, work=work
    )
    log.info("host_recipe_apply_started", host=host.name, recipe=meta.id, operation=operation_id)
    return {"operation_id": operation_id}
