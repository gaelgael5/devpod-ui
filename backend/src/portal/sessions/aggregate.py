"""Agrégation des sessions actives : conteneurs (tmux), hosts admin, VM de test.

Énumère les workspaces **déclarés** (source de vérité = table `workspaces`, pas
`workspace_status`) puis sonde tmux en direct, best-effort et en concurrence. Un
workspace injoignable n'interrompt pas l'agrégation. Une session vivante sous un
workspace qui n'est PAS suivi `running` (ex. statut `unknown`) est marquée
`orphan` : c'est le cas des sessions oubliées par le registre de statut.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from ..db.engine import _get_engine
from ..db.test_hosts import list_all_test_hosts, list_test_hosts_for_login
from ..db.user_config import list_workspace_refs
from ..db.workspace_status import list_all_status_db, list_by_login_db
from ..devpod.exec import tmux as _tmux
from ..devpod.exec import warm_tunnel, ws_exec
from .registry import AttachKey, attached_index

_log = structlog.get_logger(__name__)


async def _list_tmux_sessions(login: str, ws_id: str) -> tuple[list[str], bool]:
    """Sessions tmux d'un workspace via SSH non-interactif.

    Réutilise la même commande que `routes/workspace_sessions.list_sessions`.
    Retourne `(sessions, reachable)`. `reachable=False` sur timeout/échec SSH —
    l'appelant décide alors s'il marque `unreachable` ou ignore silencieusement.
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


async def _workspace_entry(
    ref: dict[str, Any], status_map: dict[str, dict[str, Any]], attached: set[AttachKey]
) -> list[dict[str, Any]]:
    """Entrées de session d'un workspace déclaré (0..N), après sonde tmux.

    - `stopped` : arrêté explicitement → aucune sonde, aucune entrée (pas de bruit) ;
    - `running` injoignable → marqueur `unreachable` (état inattendu) ;
    - non-`running` injoignable → ignoré (orphelin non confirmé) ;
    - joignable : une entrée par session tmux, `orphan=True` si le statut ≠ running.
    """
    login = ref["login"]
    ws_id = f"{login}-{ref['name']}"
    st = status_map.get(ws_id) or {}
    status = st.get("status") or "unknown"
    host = st.get("host_name") or ref.get("host") or None
    if status == "stopped":
        return []

    sessions, reachable = await _list_tmux_sessions(login, ws_id)
    if not reachable:
        if status == "running":
            return [
                {
                    "family": "workspace",
                    "target": ws_id,
                    "owner": login,
                    "host": host,
                    "session": None,
                    "attached": False,
                    "unreachable": True,
                }
            ]
        return []

    orphan = status != "running"
    return [
        {
            "family": "workspace",
            "target": ws_id,
            "owner": login,
            "host": host,
            "session": name,
            "attached": ("workspace", ws_id, name) in attached,
            "orphan": orphan,
        }
        for name in sessions
    ]


async def _workspace_sessions(
    refs: list[dict[str, Any]], status_map: dict[str, dict[str, Any]], attached: set[AttachKey]
) -> list[dict[str, Any]]:
    """Sonde tous les workspaces déclarés en concurrence, aplati en une liste."""
    batches = await asyncio.gather(*(_workspace_entry(ref, status_map, attached) for ref in refs))
    return [entry for batch in batches for entry in batch]


def _host_sessions(attached: set[AttachKey]) -> list[dict[str, Any]]:
    """Nœuds admin joignables en terminal (type ssh) — vue admin uniquement.

    Exclut les VM de test (`usage="tests"`) : ce sont aussi des hosts ssh, mais
    elles sont déjà couvertes par la famille `test` — sans ce filtre elles
    apparaîtraient en double (famille `host` + famille `test`).
    """
    from ..config.store import load_global

    out: list[dict[str, Any]] = []
    for host in load_global().hosts:
        if host.type != "ssh" or host.usage == "tests":
            continue
        out.append(
            {
                "family": "host",
                "target": host.name,
                "owner": "admin",
                "host": host.name,
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
                "host": host_name,
                "workspace": workspace_name,
                "session": None,
                "attached": ("test", host_name, None) in attached,
            }
        )
    return out


def _warm_running_tunnels(
    refs: list[dict[str, Any]], status_map: dict[str, dict[str, Any]]
) -> None:
    """Pré-chauffe les tunnels SSH des workspaces suivis `running` (fire-and-forget).

    On ne chauffe QUE les running : chauffer un workspace `unknown`/down monterait
    un tunnel voué à échouer. Les workspaces non-running sont sondés directement.
    """
    for ref in refs:
        ws_id = f"{ref['login']}-{ref['name']}"
        if (status_map.get(ws_id) or {}).get("status") != "running":
            continue
        # create_task : best-effort, warm_tunnel ne lève jamais.
        asyncio.create_task(warm_tunnel(ref["login"], ws_id))


async def list_sessions(*, login: str, is_admin: bool) -> list[dict[str, Any]]:
    """Agrège toutes les sessions visibles par l'appelant.

    - conteneurs : workspaces **déclarés** de `login` (tous les users si admin),
      sondés tmux en direct — une session vivante hors statut `running` est
      marquée `orphan` ;
    - hosts : uniquement en vue admin ;
    - VM de test : celles de `login` (toutes si admin).
    """
    attached = attached_index(owner=None if is_admin else login)

    async with _get_engine().connect() as conn:
        refs = await list_workspace_refs(None if is_admin else login, conn)
        status_rows = (
            await list_all_status_db(conn) if is_admin else await list_by_login_db(login, conn)
        )
        test_rows = (
            await list_all_test_hosts(conn)
            if is_admin
            else await list_test_hosts_for_login(login, conn)
        )

    status_map = {r["ws_id"]: r for r in status_rows if r.get("ws_id")}

    # Pré-chauffe avant l'énumération tmux : les tunnels chauffent pendant qu'on
    # interroge, best-effort, sans bloquer.
    _warm_running_tunnels(refs, status_map)

    result: list[dict[str, Any]] = []
    result.extend(await _workspace_sessions(refs, status_map, attached))
    if is_admin:
        result.extend(_host_sessions(attached))
    result.extend(_test_sessions(test_rows, attached))
    return result
