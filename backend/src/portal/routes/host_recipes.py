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

from ..auth.rbac import UserInfo, require_admin, require_user
from ..config.models import HostConfig
from ..config.store import load_global
from ..db.engine import get_conn
from ..db.recipes import load_recipes_as_dict
from ..db.test_hosts import is_owned_test_host, workspace_context_for_host
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


def _read_install_script(recipe_id: str, login: str) -> str | None:
    """Contenu de `install.sh`, ou None si la recette n'en porte pas.

    Lu depuis le catalogue synchronisé sur disque, jamais depuis la requête.

    Le `login` est celui de l'appelant, et il est OBLIGATOIRE : `locate_recipe_dir`
    cherche d'abord dans le catalogue personnel via `safe_user_path`, qui valide
    le login par regex et LÈVE sur une chaîne vide. Passer `""` faisait donc
    remonter un 500 au lieu de trouver la recette partagée.
    """
    # `locate_recipe_dir` applique déjà la garde anti-traversal via safe_user_path.
    directory = locate_recipe_dir(login, recipe_id)
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


async def _catalogue_pour_host(
    host: HostConfig, login: str, conn: AsyncConnection
) -> dict[str, Any]:
    """Recettes applicables a cette machine, et celles qu'elle porte deja."""
    catalogue = await _load_host_recipes(login, conn)
    available = [
        {"id": m.id, "version": m.version, "description": m.description}
        for m in catalogue.values()
        if m.applies_to_host(host.usage)
    ]
    return {"installed": await _probe_state(host), "available": available}


async def _lancer_application(
    host: HostConfig,
    recipe_id: str,
    options: dict[str, str],
    login: str,
    conn: AsyncConnection,
) -> str:
    """Valide puis lance l'application ; retourne l'identifiant d'operation."""
    if not _RECIPE_ID_RE.fullmatch(recipe_id):
        raise HTTPException(
            status_code=422, detail=f"Identifiant de recette invalide: {recipe_id!r}"
        )
    catalogue = await _load_host_recipes(login, conn)
    meta = _require_applicable(catalogue.get(recipe_id), recipe_id, host)

    # Le contexte du workspace alimente les options qui le declarent (`from:`).
    # Lu ici, tant que la connexion est ouverte — `work()` s'execute en tache de
    # fond, apres sa fermeture — et resolu des maintenant pour que le refus
    # d'une valeur invalide arrive avant le lancement de l'operation.
    contexte = await workspace_context_for_host(host.name, conn)

    try:
        resolve_options(meta, options, contexte)
    except HostApplyError as exc:
        # Refuse tout de suite : une option invalide n'a pas a etre decouverte
        # dans le journal d'une operation lancee pour rien.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    script = _read_install_script(recipe_id, login)
    if script is None:
        raise HTTPException(
            status_code=422, detail=f"Recette {recipe_id!r} sans install.sh — rien a appliquer"
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
                options=options,
                context=contexte,
            )
        except HostApplyError as exc:
            raise RuntimeError(str(exc)) from exc
        await emit_event(
            "host_recipe.applied",
            actor=login,
            subject={
                "host": host.name,
                "recipe": meta.id,
                "version": result.version,
                "changed": result.changed,
            },
        )
        return {"changed": result.changed, "version": result.version}

    operation_id = await _launch(
        kind="host_recipe_apply", workspace=host.name, owner_login=login, work=work
    )
    log.info("host_recipe_apply_started", host=host.name, recipe=meta.id, operation=operation_id)
    return operation_id


@router.get("/hosts/{name}/recipes")
async def list_host_recipes(
    name: str,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Recettes applicables a cette machine, et celles qu'elle porte deja."""
    host = _load_host(name)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} introuvable")
    return await _catalogue_pour_host(host, user.login, conn)


@router.post("/hosts/{name}/recipes/{recipe_id}", status_code=202)
async def apply_host_recipe(
    name: str,
    recipe_id: str,
    body: ApplyRecipeRequest | None = None,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    """Lance l'application et rend la main sur un identifiant d'operation."""
    host = _load_host(name)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} introuvable")
    options = body.options if body else {}
    oid = await _lancer_application(host, recipe_id, options, user.login, conn)
    return {"operation_id": oid}


# ─── Variante utilisateur : machines de test d'un workspace qu'il possede ─────
#
# Poser une recette de la galerie sur SA machine de test n'a pas a passer par un
# administrateur — c'est sa machine. La garde n'est donc pas le role mais la
# PROPRIETE : deux controles, et il en faut DEUX.
#
# `_require_ws_and_host` ne verifie que le WORKSPACE — il valide `host_name` par
# regex sans jamais le rapprocher de quoi que ce soit. Croire l'inverse a ouvert
# une faille : tout utilisateur pouvait viser n'importe quelle machine de
# l'inventaire, y compris celle d'un autre locataire ou un noeud du portail, et
# y faire executer une recette avec les droits d'administration.
#
# `is_owned_test_host` est le second, celui qui rattache la machine au couple
# (login, workspace) — le meme predicat que les routes soeurs de `test_vm.py`.
# Proprietaire et non simple destinataire d'un partage : il s'agit d'execution
# privilegiee, un workspace a qui la VM est seulement partagee n'y a pas droit.
#
# Le reste — familles declarees, preconditions, validation des parametres — est
# rigoureusement le meme code que cote admin.

me_router = APIRouter(tags=["host-recipes"])


async def _host_de_mon_workspace(
    ws: str, host_name: str, login: str, conn: AsyncConnection
) -> HostConfig:
    from .test_vm import _require_ws_and_host

    await _require_ws_and_host(ws, host_name, login)
    # Avant TOUTE connexion a la machine : la sonde SSH du catalogue part sinon
    # vers un host qu'on n'a pas le droit de toucher.
    if not await is_owned_test_host(login, ws, host_name, conn):
        raise HTTPException(
            status_code=404, detail=f"Machine {host_name!r} non rattachee a {ws!r}"
        )
    host = _load_host(host_name)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Machine {host_name!r} introuvable")
    return host


@me_router.get("/workspaces/{ws}/test-hosts/{host_name}/recipes")
async def list_my_test_host_recipes(
    ws: str,
    host_name: str,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    host = await _host_de_mon_workspace(ws, host_name, user.login, conn)
    return await _catalogue_pour_host(host, user.login, conn)


@me_router.post("/workspaces/{ws}/test-hosts/{host_name}/recipes/{recipe_id}", status_code=202)
async def apply_my_test_host_recipe(
    ws: str,
    host_name: str,
    recipe_id: str,
    body: ApplyRecipeRequest | None = None,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    host = await _host_de_mon_workspace(ws, host_name, user.login, conn)
    options = body.options if body else {}
    oid = await _lancer_application(host, recipe_id, options, user.login, conn)
    return {"operation_id": oid}
