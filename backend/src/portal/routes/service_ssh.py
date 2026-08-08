"""API de consommation des coordonnées SSH (connecteur Termix, epic T4).

Endpoints **service** que le connecteur appelle avec la **clé API admin**
(`require_admin_or_api_key` → bypass de scope, modèle « profil admin » docflow) :
lecture des coordonnées de connexion des hosts de test, workspaces et sessions,
et **reveal** du mot de passe root d'un host — le tout **audité**.

La compartimentation par utilisateur n'est PAS faite ici (l'admin lit tout) : elle
est appliquée côté Termix (provisioning par `sub`), cf. décisions verrouillées de l'epic.
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_admin_or_api_key
from ..config.store import load_global
from ..db.engine import _get_engine, get_conn
from ..db.mcp_audit import record as audit_record
from ..db.test_hosts import list_all_test_hosts
from ..db.workspace_status import list_running_db
from ..secrets.system import reveal_system_secret
from ..sessions.aggregate import probe_workspace_sessions

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["service-ssh"])

_Caller = Annotated[UserInfo, Depends(require_admin_or_api_key)]
_Conn = Annotated[AsyncConnection, Depends(get_conn)]


async def _audit(conn: AsyncConnection, actor: str, action: str, target: str | None, status: str,
                 error: str | None = None) -> None:
    await audit_record(
        conn,
        apikey_id=None,
        owner_login=actor,
        namespaced_name=action,
        backend_id=target,
        backend_key_id=None,
        latency_ms=None,
        status=status,
        error=error,
    )


@router.get("/ssh/hosts")
async def list_ssh_hosts(caller: _Caller, conn: _Conn) -> list[dict[str, Any]]:
    """Coordonnées SSH des hosts de test (adresse = user@host stockée à l'édition connexion)."""
    addr_by_host = {h.name: h.address for h in load_global().hosts}
    rows = await list_all_test_hosts(conn)
    result = [
        {
            "login": login,
            "workspace": ws_name,
            "host_name": host_name,
            "alias": alias or host_name,
            "address": addr_by_host.get(host_name, ""),
            "has_password": True,
        }
        for login, ws_name, host_name, alias in rows
    ]
    await _audit(conn, caller.login, "service.ssh.hosts.list", None, "ok")
    return result


@router.get("/ssh/workspaces")
async def list_ssh_workspaces(caller: _Caller, conn: _Conn) -> list[dict[str, Any]]:
    """Coordonnées des workspaces connectables (running) : ws_id, nœud, hostname."""
    running = await list_running_db(conn)
    result = [
        {
            "ws_id": r.get("ws_id"),
            "login": r.get("login"),
            "workspace": (r.get("ws_id") or "").removeprefix(f"{r.get('login') or ''}-"),
            "node": r.get("host_name"),
            "hostname": r.get("hostname"),
            "status": r.get("status"),
        }
        for r in running
    ]
    await _audit(conn, caller.login, "service.ssh.workspaces.list", None, "ok")
    return result


@router.get("/ssh/sessions")
async def list_ssh_sessions(caller: _Caller, conn: _Conn) -> list[dict[str, Any]]:
    """Sessions tmux vivantes par workspace running (best-effort, sonde joignable)."""
    running = await list_running_db(conn)
    result: list[dict[str, Any]] = []
    for r in running:
        ws_id = r.get("ws_id") or ""
        login = r.get("login") or ""
        if not ws_id or not login:
            continue
        try:
            rc, sessions = await probe_workspace_sessions(login, ws_id)
        except Exception:
            continue
        if rc != 0:
            continue
        result.append(
            {
                "ws_id": ws_id,
                "login": login,
                "workspace": ws_id.removeprefix(f"{login}-"),
                "sessions": sessions,
            }
        )
    await _audit(conn, caller.login, "service.ssh.sessions.list", None, "ok")
    return result


@router.post("/ssh/hosts/{host_name}/reveal-password")
async def reveal_host_password(host_name: str, caller: _Caller) -> dict[str, str]:
    """Révèle le mot de passe root d'un host sous clé admin. Audité (ok/denied)."""
    try:
        async with _get_engine().connect() as conn:
            value = await reveal_system_secret(f"host.{host_name}.root-password", conn)
    except KeyError:
        async with _get_engine().begin() as conn:
            await _audit(
                conn, caller.login, "service.ssh.host.reveal_password", host_name, "denied",
                "not_found",
            )
        raise HTTPException(status_code=404, detail="mot de passe introuvable") from None
    async with _get_engine().begin() as conn:
        await _audit(conn, caller.login, "service.ssh.host.reveal_password", host_name, "ok")
    _log.info("service_ssh_password_revealed", host=host_name, by=caller.login)
    return {"password": value}
