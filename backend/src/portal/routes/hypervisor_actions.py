"""Exécution des actions déclarées par un type d'hyperviseur.

Une action est un descripteur JSON du même format que le script de création.
Elle se déclenche à deux endroits selon sa cible :

- `hyperviseur` — depuis la liste des hyperviseurs, sur la machine hôte ;
- `machine`     — depuis la ligne d'un nœud, contre la VM qui le porte.

Les deux passent par le même chemin que la création et la destruction d'une VM
(`routes/proxmox.py`) : descripteur téléchargé avec épinglage DNS, placeholders
substitués, commandes streamées en SSH **sur l'hyperviseur**. Une action
machine ne s'exécute pas sur la VM : c'est l'hyperviseur qui la redimensionne.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth.rbac import UserInfo, require_admin
from ..config.models import GlobalConfig, HostConfig, Hypervisor, HypervisorAction
from ..config.store import load_global
from ..settings import get_settings
from .proxmox import (
    ExecuteRequest,
    _ssh_stream,
    _substitute,
    fetch_script_spec,
    resolve_option_scripts,
)

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])


class ActionSummary(BaseModel):
    """Ce dont l'IHM a besoin pour proposer une action, sans relire le type."""

    slug: str
    label: str
    cible: str


# ─── Résolution ───────────────────────────────────────────────────────────────


def _action_du_type(
    cfg: GlobalConfig,
    node: Hypervisor,
    action_slug: str,
    cible_attendue: str,
) -> HypervisorAction:
    """Retrouve une action du type de `node`, ou lève.

    Le contrôle de cible n'est pas cosmétique : les deux familles portent des
    scripts qui n'attendent pas les mêmes placeholders. Une action machine
    lancée depuis la page des hyperviseurs recevrait un `VMID` vide et
    s'exécuterait quand même — sur l'hôte.
    """
    if not node.hypervisor_type:
        raise HTTPException(
            status_code=404, detail=f"Hypervisor {node.name!r} has no type configured"
        )
    hyp_type = next((t for t in cfg.hypervisor_types if t.name == node.hypervisor_type), None)
    if hyp_type is None:
        raise HTTPException(
            status_code=404, detail=f"Hypervisor type {node.hypervisor_type!r} not found"
        )
    action = next((a for a in hyp_type.actions if a.slug == action_slug), None)
    if action is None:
        raise HTTPException(
            status_code=404,
            detail=f"Action {action_slug!r} not found on hypervisor type {hyp_type.name!r}",
        )
    if action.cible != cible_attendue:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Action {action_slug!r} a pour cible {action.cible!r}, "
                f"elle ne s'exécute pas ici (cible attendue : {cible_attendue!r})"
            ),
        )
    if not action.script:
        raise HTTPException(
            status_code=404, detail=f"Action {action_slug!r} has no script configured"
        )
    return action


def _hyperviseur(cfg: GlobalConfig, name: str) -> Hypervisor:
    node = next((n for n in cfg.hypervisors if n.name == name), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor {name!r} not found")
    return node


def _host_et_son_hyperviseur(cfg: GlobalConfig, name: str) -> tuple[HostConfig, Hypervisor]:
    """Host + hyperviseur qui l'héberge, ou 404/409.

    409 et non 404 quand le host n'a ni `proxmox_node` ni `vmid` : le host
    existe, c'est l'action qui n'a pas de sens — un nœud enrôlé à la main n'est
    la VM de personne.
    """
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")
    if not host.proxmox_node or not host.vmid:
        raise HTTPException(
            status_code=409,
            detail=f"Host {name!r} n'a pas d'hyperviseur : aucune action machine exécutable",
        )
    node = next((n for n in cfg.hypervisors if n.name == host.proxmox_node), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Hypervisor {host.proxmox_node!r} not found")
    return host, node


# ─── Exécution ────────────────────────────────────────────────────────────────


def _args_portail(cfg: GlobalConfig, node: Hypervisor) -> dict[str, str]:
    settings = get_settings()
    return {
        "PORTAL_URL": cfg.server.external_url,
        "PORTAL_TOKEN": settings.portal_api_key,
        "PORTAL_PVE_NODE": node.name,
    }


def _reponse_streamee(
    node: Hypervisor,
    spec: dict[str, object],
    args: dict[str, str],
) -> StreamingResponse:
    """Substitue, affiche les commandes (token masqué) puis streame la sortie SSH."""
    commands_raw: list[str] = list(spec.get("commands", []))  # type: ignore[arg-type]
    commands = [_substitute(cmd, args) for cmd in commands_raw]
    redacted = {**args, "PORTAL_TOKEN": "***"}
    display_commands = [_substitute(cmd, redacted) for cmd in commands_raw]

    async def _stream() -> AsyncIterator[bytes]:
        lines = "\n".join(f"    {cmd}" for cmd in display_commands)
        header = f"==> Commandes exécutées :\n{lines}\n\n"
        yield header.encode("utf-8")
        async for chunk in _ssh_stream(node, commands):
            yield chunk

    return StreamingResponse(_stream(), media_type="text/plain; charset=utf-8")


# ─── Actions sur l'hyperviseur ────────────────────────────────────────────────


@router.get("/hypervisors/{name}/actions")
async def list_hypervisor_actions(
    name: str,
    user: UserInfo = Depends(require_admin),
) -> list[ActionSummary]:
    """Actions de cible `hyperviseur` proposées par le type de cette machine."""
    cfg = load_global()
    node = _hyperviseur(cfg, name)
    hyp_type = next((t for t in cfg.hypervisor_types if t.name == node.hypervisor_type), None)
    if hyp_type is None:
        return []
    return [
        ActionSummary(slug=a.slug, label=a.label, cible=a.cible)
        for a in hyp_type.actions
        if a.cible == "hyperviseur" and a.script
    ]


@router.get("/hypervisors/{name}/actions/{action_slug}/script")
async def get_hypervisor_action_script(
    name: str,
    action_slug: str,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    """Spec JSON de l'action, options dynamiques résolues sur cette machine."""
    cfg = load_global()
    node = _hyperviseur(cfg, name)
    action = _action_du_type(cfg, node, action_slug, "hyperviseur")
    spec = await fetch_script_spec(action.script)
    await resolve_option_scripts(spec, [node])
    return spec


@router.post("/hypervisors/{name}/actions/{action_slug}/execute")
async def execute_hypervisor_action(
    name: str,
    action_slug: str,
    body: ExecuteRequest,
    user: UserInfo = Depends(require_admin),
) -> StreamingResponse:
    cfg = load_global()
    node = _hyperviseur(cfg, name)
    action = _action_du_type(cfg, node, action_slug, "hyperviseur")
    spec = await fetch_script_spec(action.script)

    args = {**body.args, **_args_portail(cfg, node)}
    _log.info(
        "hypervisor_action_execute",
        node=name,
        action=action_slug,
        by=user.login,
    )
    return _reponse_streamee(node, spec, args)


# ─── Actions sur les machines créées par l'hyperviseur ────────────────────────


@router.get("/hosts/{name}/actions")
async def list_host_actions(
    name: str,
    user: UserInfo = Depends(require_admin),
) -> list[ActionSummary]:
    """Actions de cible `machine` applicables à ce nœud.

    Liste vide — et non 409 — pour un host sans hyperviseur : l'IHM interroge
    toutes les lignes pour savoir lesquelles portent un menu, une erreur n'y
    apprendrait rien.
    """
    cfg = load_global()
    host = next((h for h in cfg.hosts if h.name == name), None)
    if host is None:
        raise HTTPException(status_code=404, detail=f"Host {name!r} not found")
    if not host.proxmox_node or not host.vmid:
        return []
    node = next((n for n in cfg.hypervisors if n.name == host.proxmox_node), None)
    if node is None or not node.hypervisor_type:
        return []
    hyp_type = next((t for t in cfg.hypervisor_types if t.name == node.hypervisor_type), None)
    if hyp_type is None:
        return []
    return [
        ActionSummary(slug=a.slug, label=a.label, cible=a.cible)
        for a in hyp_type.actions
        if a.cible == "machine" and a.script
    ]


@router.get("/hosts/{name}/actions/{action_slug}/script")
async def get_host_action_script(
    name: str,
    action_slug: str,
    user: UserInfo = Depends(require_admin),
) -> dict[str, object]:
    cfg = load_global()
    _host, node = _host_et_son_hyperviseur(cfg, name)
    action = _action_du_type(cfg, node, action_slug, "machine")
    spec = await fetch_script_spec(action.script)
    await resolve_option_scripts(spec, [node])
    return spec


@router.post("/hosts/{name}/actions/{action_slug}/execute")
async def execute_host_action(
    name: str,
    action_slug: str,
    body: ExecuteRequest,
    user: UserInfo = Depends(require_admin),
) -> StreamingResponse:
    cfg = load_global()
    host, node = _host_et_son_hyperviseur(cfg, name)
    action = _action_du_type(cfg, node, action_slug, "machine")
    spec = await fetch_script_spec(action.script)

    # `VMID` d'abord depuis le host : une action machine s'applique à CETTE
    # machine, l'utilisateur n'a pas à la désigner et ne doit pas pouvoir en
    # désigner une autre depuis le formulaire d'arguments.
    args = {**body.args, **_args_portail(cfg, node), "VMID": host.vmid}
    _log.info(
        "host_action_execute",
        host=name,
        vmid=host.vmid,
        node=node.name,
        action=action_slug,
        by=user.login,
    )
    return _reponse_streamee(node, spec, args)
