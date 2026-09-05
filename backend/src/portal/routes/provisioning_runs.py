"""Opérations de provisionnement — consultation et reprise (ticket 6).

Un provisionnement rend un identifiant d'opération (le `run_id` du registre) ;
son état se consulte ici sans que l'appelant reste connecté. Les échecs sont
listables, et chaque état dit sa suite : `echec_avant_creation` se rejoue,
`echec_apres_creation` se reprend ou se détruit, `indetermine` attend une
décision humaine — jamais de rejeu automatique.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin
from ..billing.executeur_proxmox import ExecuteurProxmox
from ..billing.orchestration import RejeuRefuse, detruire_reste, rejouer
from ..db.engine import get_conn
from ..db.provisioning_runs import lire, lister, peut_rejouer

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])


def _vue(run: dict[str, Any]) -> dict[str, Any]:
    """Vue API d'une tentative. `provider_ref` est opaque : il est montré tel
    quel (trace d'exploitation), jamais interprété."""
    return {
        **{k: v for k, v in run.items() if k not in ("created_at", "updated_at")},
        "created_at": run["created_at"].isoformat(),
        "updated_at": run["updated_at"].isoformat(),
        "rejouable": peut_rejouer(str(run["state"])),
        "destructible": bool(
            run["state"] in ("echec_apres_creation", "indetermine")
            and run.get("provider_ref")
            and run.get("provider")
        ),
    }


@router.get("/admin/provisioning/runs")
async def list_runs(
    state: str | None = None,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> list[dict[str, Any]]:
    return [_vue(r) for r in await lister(conn, state=state)]


@router.get("/admin/provisioning/runs/{run_id}")
async def get_run(
    run_id: int,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    run = await lire(run_id, conn)
    if run is None:
        raise HTTPException(status_code=404, detail=f"tentative {run_id} introuvable")
    return _vue(run)


@router.post("/admin/provisioning/runs/{run_id}/rejouer")
async def rejouer_run(
    run_id: int,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    _log.info("provisioning_rejeu_demande", run_id=run_id, by=user.login)
    try:
        resultat = await rejouer(run_id, conn, ExecuteurProxmox())
    except RejeuRefuse as exc:
        # 409 : l'état n'autorise pas le rejeu — le message dit la suite attendue.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": run_id, "state": resultat.state, "erreur": resultat.erreur}


@router.post("/admin/provisioning/runs/{run_id}/detruire")
async def detruire_run(
    run_id: int,
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    _log.info("provisioning_destruction_demandee", run_id=run_id, by=user.login)
    try:
        resultat = await detruire_reste(run_id, conn)
    except RejeuRefuse as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": run_id, "state": resultat.state}
