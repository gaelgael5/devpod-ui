"""Agrégation des sessions actives : conteneurs (tmux), hosts admin, VM de test.

Énumère les workspaces **déclarés** (source de vérité = table `workspaces`, pas
`workspace_status`) puis sonde tmux en direct, best-effort et en concurrence. Un
workspace injoignable n'interrompt pas l'agrégation. Une session vivante sous un
workspace qui n'est PAS suivi `running` (ex. statut `unknown`) est marquée
`orphan` : c'est le cas des sessions oubliées par le registre de statut.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

import structlog

from ..db.engine import _get_engine
from ..db.test_hosts import list_all_test_hosts, list_test_hosts_for_login
from ..db.user_config import list_workspace_refs
from ..db.workspace_status import list_all_status_db, list_by_login_db
from ..devpod.exec import NO_TMUX_SERVER_RCS, TIMEOUT_RC, warm_tunnel, ws_exec
from ..devpod.exec import tmux as _tmux
from ..devpod.host_exec import run_host_command
from ..settings import get_settings
from .registry import AttachKey, attached_index

_log = structlog.get_logger(__name__)


async def _list_tmux_sessions(login: str, ws_id: str, host: str | None) -> tuple[list[str], bool]:
    """Sessions tmux d'un workspace via SSH non-interactif.

    Retourne `(sessions, reachable)`. Le rc de tmux n'est PAS masqué (pas de
    `|| true`) : c'est lui qui différencie les états (bug 807fed1c) —
    - 0 → sessions listées ;
    - 1/127 (aucun serveur tmux / tmux absent) → joignable, zéro session (normal) ;
    - 255 (transport SSH) ou TIMEOUT_RC → workspace injoignable, `reachable=False`.
    """
    try:
        rc, sessions = await probe_workspace_sessions(login, ws_id)
    except Exception:
        _log.warning("sessions_tmux_list_failed", ws_id=ws_id, host=host, exc_info=True)
        return [], False
    if rc in NO_TMUX_SERVER_RCS:
        _log.debug("sessions_tmux_no_server", ws_id=ws_id, host=host, rc=rc)
        return [], True
    if rc != 0:
        _log.warning(
            "sessions_probe_unreachable",
            ws_id=ws_id,
            host=host,
            rc=rc,
            reason="timeout" if rc == TIMEOUT_RC else "ssh_transport",
        )
        return [], False
    return sessions, True


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

    sessions, reachable = await _list_tmux_sessions(login, ws_id, host)
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


# Marqueur imprimé par la sonde quand tmux n'est pas installé sur le host —
# distinct de « aucune session » (l'UI affiche alors « non persistant, installez tmux »).
_NO_TMUX_MARKER = "__PORTAL_NO_TMUX__"


async def _probe_host_tmux(host: Any) -> list[str] | Literal["no-tmux"] | None:
    """Sessions tmux d'un host admin, "no-tmux" si tmux absent, None si sonde impossible.

    Best-effort court : host sans SSH portail (pas d'adresse/cert) ou injoignable
    → None, l'appelant retombe sur l'entrée statique historique.
    """
    if not getattr(host, "address", "") or not getattr(host, "host_cert_slug", ""):
        return None
    probe = (
        "if command -v tmux >/dev/null 2>&1; "
        "then tmux list-sessions -F '#{session_name}' 2>/dev/null || true; "
        f"else echo {_NO_TMUX_MARKER}; fi"
    )
    try:
        rc, out, _err = await run_host_command(host, probe, timeout=8.0)
    except Exception:
        _log.info("sessions_host_probe_failed", host=host.name)
        return None
    if rc != 0:
        return None
    if _NO_TMUX_MARKER in out:
        return "no-tmux"
    return [s for s in out.strip().splitlines() if s]


async def _host_sessions(attached: set[AttachKey]) -> list[dict[str, Any]]:
    """Nœuds admin joignables en terminal (type ssh) — vue admin uniquement.

    Les terminaux host tournent dans tmux : chaque host est sondé (concurrence,
    best-effort) et expose une entrée par session tmux vivante. Sonde impossible
    → entrée statique (le host reste ouvrable, session `main` créée à l'attache).
    Exclut les VM de test (`usage="tests"`) : ce sont aussi des hosts ssh, mais
    elles sont déjà couvertes par la famille `test` — sans ce filtre elles
    apparaîtraient en double (famille `host` + famille `test`).
    """
    from ..config.store import load_global

    hosts = [h for h in load_global().hosts if h.type == "ssh" and h.usage != "tests"]
    probed = await asyncio.gather(*(_probe_host_tmux(h) for h in hosts))

    out: list[dict[str, Any]] = []
    for host, sessions in zip(hosts, probed, strict=True):
        if isinstance(sessions, list) and sessions:
            out.extend(
                {
                    "family": "host",
                    "target": host.name,
                    "owner": "admin",
                    "host": host.name,
                    "session": name,
                    "attached": ("host", host.name, name) in attached,
                }
                for name in sessions
            )
        else:
            out.append(
                {
                    "family": "host",
                    "target": host.name,
                    "owner": "admin",
                    "host": host.name,
                    "session": None,
                    # Sonde muette mais pont ouvert (n'importe quelle session) → attaché.
                    "attached": any(k[0] == "host" and k[1] == host.name for k in attached),
                    # tmux absent sur le host → l'UI prévient (session non persistante).
                    "no_tmux": sessions == "no-tmux",
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


# Références fortes des tâches de fond (une tâche asyncio non référencée peut
# être ramassée par le GC avant de s'exécuter) — partagé avec reachability_hint
# plus bas, même besoin.
_background_probes: set[asyncio.Task[Any]] = set()


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
        # create_task : best-effort, warm_tunnel ne lève jamais. Référencée dans
        # _background_probes (bug fire-and-forget) : sans ça le GC peut annuler
        # le pré-chauffage avant son terme.
        task = asyncio.create_task(warm_tunnel(ref["login"], ws_id))
        _background_probes.add(task)
        task.add_done_callback(_background_probes.discard)


# Découplage polling front / sonde réelle (enabler be1112a5) : le front peut
# poller à volonté, la sonde SSH ne repart qu'à l'expiration du TTL. Anti-dogpile :
# un seul refresh concurrent par clé (login, is_admin), les lectures simultanées
# attendent le même résultat. Invalidé sur mutation (création/fermeture).
_CACHE_TTL_S = 5.0
_cache: dict[tuple[str, bool], tuple[float, list[dict[str, Any]]]] = {}
_cache_locks: dict[tuple[str, bool], asyncio.Lock] = {}


# Cache par-workspace de la sonde tmux brute — GET /me/workspaces/{name}/sessions
# est pollé toutes les 5 s par CHAQUE onglet terminal ouvert ; l'agrégat /sessions
# sonde les mêmes workspaces. Une seule sonde par ws_id et par TTL pour tous.
_WS_PROBE_TTL_S = 4.0
_ws_probe_cache: dict[str, tuple[float, tuple[int, list[str]]]] = {}
_ws_probe_locks: dict[str, asyncio.Lock] = {}


async def probe_workspace_sessions(login: str, ws_id: str) -> tuple[int, list[str]]:
    """(rc brut, sessions) de la sonde tmux d'un workspace, caché TTL court.

    Le rc n'est pas interprété ici (voir NO_TMUX_SERVER_RCS / TIMEOUT_RC côté
    appelants) ; un rc d'échec est aussi caché — pas de marteau sur un host mort.
    """
    hit = _ws_probe_cache.get(ws_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    lock = _ws_probe_locks.setdefault(ws_id, asyncio.Lock())
    async with lock:
        hit = _ws_probe_cache.get(ws_id)  # un refresh concurrent a pu aboutir
        if hit and hit[0] > time.monotonic():
            return hit[1]
        rc, output = await ws_exec(
            login,
            ws_id,
            _tmux("list-sessions -F '#{session_name}' 2>/dev/null"),
        )
        sessions = [s for s in output.strip().splitlines() if s] if rc == 0 else []
        result = (rc, sessions)
        _ws_probe_cache[ws_id] = (time.monotonic() + _WS_PROBE_TTL_S, result)
        return result


# Fenêtre de validité du verdict de réachabilité pour l'AFFICHAGE (bug 2846f916) —
# plus longue que le TTL de sonde : un verdict vieux de 30 s reste un signal utile.
_REACHABILITY_WINDOW_S = 60.0


def reachability_hint(login: str, ws_id: str) -> bool | None:
    """Verdict de réachabilité d'un workspace, dérivé de la dernière sonde tmux.

    True = joignable, False = injoignable (transport SSH / timeout), None = pas de
    verdict récent. N'attend JAMAIS une sonde : lit le cache, et si le verdict est
    absent ou périmé, déclenche une sonde en arrière-plan (dédupliquée par le
    verrou + cache de probe_workspace_sessions) — le prochain poll de statut la
    verra. Surcouche d'affichage uniquement : n'écrit jamais le statut en base
    (bug 2846f916 : « running » ne doit plus masquer un host injoignable).
    """
    hit = _ws_probe_cache.get(ws_id)
    now = time.monotonic()
    verdict: bool | None = None
    if hit is not None:
        probed_at = hit[0] - _WS_PROBE_TTL_S
        if now - probed_at <= _REACHABILITY_WINDOW_S:
            rc = hit[1][0]
            verdict = rc == 0 or rc in NO_TMUX_SERVER_RCS
    if hit is None or hit[0] <= now:
        task = asyncio.create_task(probe_workspace_sessions(login, ws_id))
        _background_probes.add(task)
        task.add_done_callback(_background_probes.discard)
    return verdict


def invalidate_sessions_cache() -> None:
    """Vide les caches : la prochaine lecture re-sonde (appelé après toute mutation)."""
    _cache.clear()
    _ws_probe_cache.clear()


def clear_sessions_cache() -> None:
    """Purge caches ET verrous. Usage tests uniquement (locks liés à l'event loop)."""
    _cache.clear()
    _cache_locks.clear()
    _ws_probe_cache.clear()
    _ws_probe_locks.clear()


async def list_sessions(*, login: str, is_admin: bool) -> list[dict[str, Any]]:
    """Agrège les sessions visibles par l'appelant, avec cache court (TTL 5 s)."""
    key = (login, is_admin)
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    lock = _cache_locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)  # un refresh concurrent vient peut-être d'aboutir
        if hit and hit[0] > time.monotonic():
            return hit[1]
        result = await _list_sessions_live(login=login, is_admin=is_admin)
        _cache[key] = (time.monotonic() + _CACHE_TTL_S, result)
        return result


async def _list_sessions_live(*, login: str, is_admin: bool) -> list[dict[str, Any]]:
    """Agrège toutes les sessions visibles par l'appelant (sonde réelle).

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
        result.extend(await _host_sessions(attached))
    result.extend(_test_sessions(test_rows, attached))
    await _attach_disk_usage(result)
    return result


async def _attach_disk_usage(entries: list[dict[str, Any]]) -> None:
    """Ajoute le ratio disque aux entrées portant une machine (hosts, ressources, VM de test).

    Lecture de la table alimentée par la sonde horaire (`nodes/disk.py`) : AUCUN
    SSH ici — l'agrégat sessions est pollé toutes les 5 s par le front, sonder le
    disque à chaque appel saturerait les nœuds.

    Un host jamais sondé n'a pas de ligne : on n'ajoute alors rien, et l'UI
    affiche « inconnu » plutôt qu'un « 0 % » qui laisserait croire à un disque
    vide. Best-effort : une erreur de lecture ne doit jamais casser la liste des
    sessions, qui reste utile sans cette décoration.
    """
    hosts = {e["host"] for e in entries if e.get("family") in ("host", "test") and e.get("host")}
    if not hosts:
        return
    try:
        from ..db import host_disk as host_disk_db

        async with _get_engine().connect() as conn:
            usage = await host_disk_db.get_all(conn)
    except Exception:
        _log.warning("sessions_disk_usage_unavailable", exc_info=True)
        return

    warn_pct = get_settings().host_disk_warn_pct
    for entry in entries:
        row = usage.get(entry.get("host") or "")
        if row is None or row.get("used_pct") is None:
            continue
        pct = int(row["used_pct"])
        entry["disk"] = {
            "total_bytes": row.get("total_bytes"),
            "used_bytes": row.get("used_bytes"),
            "avail_bytes": row.get("avail_bytes"),
            "used_pct": pct,
            "warn": pct >= warn_pct,
            "measured_at": row["measured_at"].isoformat() if row.get("measured_at") else None,
            # Dernière sonde en échec : la mesure affichée est la précédente.
            "stale_error": row.get("error"),
        }
