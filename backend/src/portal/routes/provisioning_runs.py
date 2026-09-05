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


@router.get("/admin/provisioning/reconciliation")
async def reconciliation(
    user: UserInfo = Depends(require_admin),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, Any]:
    """Les trois vues confrontées — portail, state OpenTofu, provider — plus
    les TTL dépassés. Cette route SIGNALE : aucune action destructrice n'existe
    ici, et une panne d'API provider ne rend pas le parc orphelin."""
    import os

    from sqlalchemy import text

    from ..config.store import load_global
    from ..provisioning.azure_inventory import AzureInventaire, InventaireIndisponible
    from ..provisioning.reconciliation import classer_ecarts, machines_expirees

    cfg = load_global()
    portail = {h.name for h in cfg.hosts if h.provider == "azure"}

    try:
        lignes = await conn.execute(text("SELECT name FROM terraform_remote_state.states"))
        state = {str(r[0]) for r in lignes}
    except Exception:  # noqa: BLE001 — schéma absent = aucun state, pas une panne
        state = set()

    provider: set[str] | None = None
    arm = {
        k: os.environ.get(k, "")
        for k in ("ARM_TENANT_ID", "ARM_CLIENT_ID", "ARM_CLIENT_SECRET", "ARM_SUBSCRIPTION_ID")
    }
    if all(arm.values()):
        try:
            provider = await AzureInventaire(
                tenant_id=arm["ARM_TENANT_ID"],
                client_id=arm["ARM_CLIENT_ID"],
                client_secret=arm["ARM_CLIENT_SECRET"],
                subscription_id=arm["ARM_SUBSCRIPTION_ID"],
            ).machines()
        except InventaireIndisponible as exc:
            _log.warning("reconciliation_provider_indisponible", error=str(exc))

    ecarts = classer_ecarts(
        portail=portail,
        state=state,
        provider=provider,
        expirees=machines_expirees(cfg.hosts),
    )
    if ecarts.orphelines or ecarts.expirees:
        _log.warning(
            "reconciliation_ecarts",
            orphelines=len(ecarts.orphelines),
            expirees=len(ecarts.expirees),
        )
    return ecarts.model_dump()


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
