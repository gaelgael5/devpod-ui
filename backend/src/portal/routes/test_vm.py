"""Création d'une VM de test attachée à un workspace (lot C+D).

L'utilisateur ne fournit que l'hyperviseur et le vmid ; tous les autres args sont
figés par le paramétrage admin (`test_host_params` du type). Le host créé est marqué
`usage=tests` et associé au workspace.
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from ..auth.rbac import UserInfo, require_user
from ..config.models import GlobalConfig
from ..config.store import load_global, load_user
from ..db.engine import _get_engine
from ..db.global_config import save_global_db
from ..db.test_hosts import assign_test_host
from ..devpod.test_vm import build_test_vm_args, map_result_to_host, parse_last_json
from ..settings import get_settings
from .proxmox import (
    _fetch_spec,
    _ssh_stream,
    _substitute,
    find_identifier_arg,
    resolve_node_script,
)

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["test-vm"])

_VMID_RE = re.compile(r"^[0-9]{1,9}$")
_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")


def _usable_type_names(cfg: GlobalConfig) -> set[str]:
    """Types d'hyperviseur prêts pour les VM de test : add_script + paramétrage."""
    return {t.name for t in cfg.hypervisor_types if t.add_script and t.test_host_params}


@router.get("/test-hypervisors")
async def list_test_hypervisors(
    user: UserInfo = Depends(require_user),
) -> list[dict[str, str]]:
    """Hyperviseurs utilisables pour créer une VM de test."""
    cfg = load_global()
    usable = _usable_type_names(cfg)
    labels = {t.name: (t.label or t.name) for t in cfg.hypervisor_types}
    return [
        {"name": n.name, "type": n.hypervisor_type, "label": labels[n.hypervisor_type]}
        for n in cfg.hypervisors
        if n.hypervisor_type in usable
    ]


@router.get("/test-hypervisors/{name}/script")
async def get_test_hypervisor_script(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    """Spec du node résolue (pour proposer les valeurs du vmid)."""
    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == name), None)
    if node is None or node.hypervisor_type not in _usable_type_names(cfg):
        raise HTTPException(status_code=404, detail=f"Test hypervisor {name!r} not available")
    return await resolve_node_script(node, cfg)


class CreateTestVmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypervisor: str
    vmid: str


@router.post("/workspaces/{ws}/test-vm")
async def create_test_vm(
    ws: str,
    body: CreateTestVmRequest,
    user: UserInfo = Depends(require_user),
) -> StreamingResponse:
    """Crée une VM de test, l'enregistre (usage=tests) et l'associe au workspace."""
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    if not _VMID_RE.fullmatch(body.vmid):
        raise HTTPException(status_code=422, detail="vmid must be numeric")

    user_cfg = await load_user(user.login)
    if not any(w.name == ws for w in user_cfg.workspaces):
        raise HTTPException(status_code=404, detail=f"Workspace {ws!r} not found")

    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == body.hypervisor), None)
    if node is None or node.hypervisor_type not in _usable_type_names(cfg):
        raise HTTPException(
            status_code=404, detail=f"Test hypervisor {body.hypervisor!r} not available"
        )
    hyp_type = next(t for t in cfg.hypervisor_types if t.name == node.hypervisor_type)

    spec = await _fetch_spec(node, cfg)
    identifier_arg = find_identifier_arg(spec)
    if identifier_arg is None:
        raise HTTPException(status_code=422, detail="Hypervisor spec has no identifier arg")

    commands_raw: list[str] = spec.get("commands", [])  # type: ignore[assignment]
    settings = get_settings()
    args = build_test_vm_args(dict(hyp_type.test_host_params), identifier_arg, body.vmid)
    args["PORTAL_URL"] = cfg.server.external_url
    args["PORTAL_TOKEN"] = settings.portal_api_key
    args["PORTAL_PVE_NODE"] = node.name
    commands = [_substitute(c, args) for c in commands_raw]
    display = [_substitute(c, {**args, "PORTAL_TOKEN": "***"}) for c in commands_raw]

    login = user.login
    _log.info("test_vm_create", login=login, ws=ws, node=node.name, vmid=body.vmid)

    async def _stream() -> AsyncIterator[bytes]:
        header = "==> Création VM de test\n" + "\n".join(f"    {c}" for c in display) + "\n\n"
        yield header.encode("utf-8")
        buf = bytearray()
        async for chunk in _ssh_stream(node, commands):
            buf.extend(chunk)
            yield chunk

        result: dict[str, Any] | None = parse_last_json(buf.decode("utf-8", errors="replace"))
        if result is None:
            yield b"\n==> ERREUR : pas de resultat JSON du script de creation\n"
            return
        host = map_result_to_host(result, body.vmid, node.name)
        if not host.name:
            yield b"\n==> ERREUR : le script n'a pas retourne de nom d'hote\n"
            return

        new_cfg = load_global()
        if any(h.name == host.name for h in new_cfg.hosts):
            yield f"\n==> ERREUR : un host nomme {host.name!r} existe deja\n".encode()
            return
        new_cfg.hosts.append(host)
        async with _get_engine().begin() as conn:
            await save_global_db(new_cfg, conn)
            await assign_test_host(login, ws, host.name, conn)
        yield (
            f"\n==> VM de test '{host.name}' creee et attachee au workspace '{ws}'\n"
        ).encode()

    return StreamingResponse(_stream(), media_type="text/plain; charset=utf-8")
