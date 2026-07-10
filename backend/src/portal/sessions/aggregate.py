"""Agrégation des sessions actives : conteneurs (tmux), hosts admin, VM de test.

Best-effort par workspace, à l'image du monitor MCP : un workspace injoignable
n'interrompt pas l'agrégation, il est marqué `unreachable`. Pré-chauffe les
tunnels SSH des workspaces running en tâche de fond (fire-and-forget).
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from ..db.engine import _get_engine
from ..db.test_hosts import list_all_test_hosts, list_test_hosts_for_login
from ..db.workspace_status import list_by_login_db, list_running_db
from ..devpod.exec import tmux as _tmux
from ..devpod.exec import warm_tunnel, ws_exec
from .registry import AttachKey, attached_index

_log = structlog.get_logger(__name__)


async def _list_tmux_sessions(login: str, ws_id: str) -> tuple[list[str], bool]:
    """Sessions tmux d'un workspace via SSH non-interactif.

    Réutilise la même commande que `routes/workspace_sessions.list_sessions`.
    Retourne `(sessions, reachable)`. `reachable=False` sur timeout/échec SSH —
    l'appelant marque alors le workspace `unreachable` sans l'exclure.
    """
    try:
        rc, output = await ws_exec(
            login,
            ws_id,
            _tmux("list-sessions -F '#{session_name}' 2>/dev/null || true"),
        )
    except Exception:
        _log.warning("sessions_tmux_list_failed", ws_id=ws_id, exc_info=True)
        return [], False
    if rc != 0:
        _log.info("sessions_tmux_list_rc", ws_id=ws_id, rc=rc)
        return [], False
    return [s for s in output.strip().splitlines() if s], True


def _running_owner(row: dict[str, Any]) -> tuple[str, str] | None:
    """(login, ws_id) d'une ligne workspace_status running, ou None si incomplet."""
    login = row.get("login") or ""
    ws_id = row.get("ws_id") or ""
    if not login or not ws_id:
        return None
    return login, ws_id


async def _workspace_sessions(
    running: list[dict[str, Any]], attached: set[AttachKey]
) -> list[dict[str, Any]]:
    """Sessions conteneur : une entrée par session tmux (ou marqueur unreachable)."""
    out: list[dict[str, Any]] = []
    for row in running:
        pair = _running_owner(row)
        if pair is None:
            continue
        login, ws_id = pair
        sessions, reachable = await _list_tmux_sessions(login, ws_id)
        if not reachable:
            out.append(
                {
                    "family": "workspace",
                    "target": ws_id,
                    "owner": login,
                    "session": None,
                    "attached": False,
                    "unreachable": True,
                }
            )
            continue
        for name in sessions:
            out.append(
                {
                    "family": "workspace",
                    "target": ws_id,
                    "owner": login,
                    "session": name,
                    "attached": ("workspace", ws_id, name) in attached,
                }
            )
    return out


def _host_sessions(attached: set[AttachKey]) -> list[dict[str, Any]]:
    """Hosts admin joignables en terminal (type ssh) — vue admin uniquement."""
    from ..config.store import load_global

    out: list[dict[str, Any]] = []
    for host in load_global().hosts:
        if host.type != "ssh":
            continue
        out.append(
            {
                "family": "host",
                "target": host.name,
                "owner": "admin",
                "session": None,
                "attached": ("host", host.name, None) in attached,
            }
        )
    return out


def _test_sessions(
    rows: list[tuple[str, str, str, str]], attached: set[AttachKey]
) -> list[dict[str, Any]]:
    """VM de test attachées à un workspace (owner = login du workspace lié)."""
    out: list[dict[str, Any]] = []
    for login, workspace_name, host_name, _alias in rows:
        out.append(
            {
                "family": "test",
                "target": host_name,
                "owner": login,
                "workspace": workspace_name,
                "session": None,
                "attached": ("test", host_name, None) in attached,
            }
        )
    return out


def _warm_running_tunnels(running: list[dict[str, Any]]) -> None:
    """Pré-chauffe les tunnels SSH des workspaces running (fire-and-forget)."""
    for row in running:
        pair = _running_owner(row)
        if pair is None:
            continue
        login, ws_id = pair
        # create_task : best-effort, warm_tunnel ne lève jamais.
        asyncio.create_task(warm_tunnel(login, ws_id))


async def list_sessions(*, login: str, is_admin: bool) -> list[dict[str, Any]]:
    """Agrège toutes les sessions visibles par l'appelant.

    - conteneurs : workspaces running de `login` (tous les users si admin) ;
    - hosts : uniquement en vue admin ;
    - VM de test : celles de `login` (toutes si admin).
    """
    attached = attached_index(owner=None if is_admin else login)

    async with _get_engine().connect() as conn:
        if is_admin:
            running = await list_running_db(conn)
            test_rows = await list_all_test_hosts(conn)
        else:
            running = [
                r for r in await list_by_login_db(login, conn) if r.get("status") == "running"
            ]
            test_rows = await list_test_hosts_for_login(login, conn)

    # Pré-chauffe avant l'énumération tmux : les tunnels chauffent pendant qu'on
    # interroge, best-effort, sans bloquer.
    _warm_running_tunnels(running)

    result: list[dict[str, Any]] = []
    result.extend(await _workspace_sessions(running, attached))
    if is_admin:
        result.extend(_host_sessions(attached))
    result.extend(_test_sessions(test_rows, attached))
    return result
