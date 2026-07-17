"""Resync à chaud des fichiers agents par écriture conteneur (spec 35b T6).

Déclenché après commit par les routes ((dé)cochage « exposé aux workspaces »,
édition d'un type d'agent) et au boot du portail (réconciliation) : pour chaque
workspace RUNNING concerné, `push_agent_files` rotationne les clefs et réécrit
les fichiers directement dans le conteneur (canal `devpod ssh`).

Un workspace arrêté est sauté, jamais en échec : le hook post-readiness du
prochain `up` le rattrape. Best-effort par workspace : un échec (conteneur
injoignable, agent stale) est loggé et n'empêche pas les autres — les clefs
révoquées côté DB restent le fail-closed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from ..config.models import GlobalConfig, WorkspaceSpec
from ..config.store import load_global, load_user
from .push import push_agent_files

_log = structlog.get_logger(__name__)


def _host_supported(spec: WorkspaceSpec, global_cfg: GlobalConfig) -> bool:
    """v1 : dépose via `devpod ssh` validée sur hosts SSH uniquement (spec 35 §10)."""
    from ..devpod.env import _find_host

    return _find_host(spec.host, global_cfg).type == "ssh"


async def _ws_running(ws_id: str) -> bool:
    from ..db.engine import _get_engine
    from ..db.workspace_status import get_status_db

    async with _get_engine().connect() as conn:
        row = await get_status_db(ws_id, conn)
    return bool(row and row.get("status") == "running")


async def _list_running() -> list[dict[str, Any]]:
    from ..db.engine import _get_engine
    from ..db.workspace_status import list_running_db

    async with _get_engine().connect() as conn:
        return await list_running_db(conn)


async def _config_unchanged(
    *, login: str, ws_id: str, agents: list[str], mcp_url: str, ws_name: str, project_root: str
) -> bool:
    """True si la config agents rendue est identique à la dernière livrée.

    Idempotence du resync : évite de rotationner les clefs MCP et de réécrire les
    fichiers quand rien n'a changé (cause n°1 des ré-authentifications au boot du
    portail). Compare une empreinte du rendu (hors token) à celle stockée. En cas
    de doute (pas d'empreinte connue, aucun type d'agent résolu), retourne False —
    on livre, jamais l'inverse (fail-safe : mieux vaut une rotation de trop).
    """
    from ..db.agent_sync import get_config_hash
    from ..db.engine import _get_engine
    from ..db.mcp_profiles import list_exposed_profiles
    from .provisioning import _load_requested_agent_types
    from .sync_state import compute_agent_fingerprint

    agent_rows = await _load_requested_agent_types(agents)
    if not agent_rows:
        return False
    async with _get_engine().connect() as conn:
        stored = await get_config_hash(conn, ws_id)
        if stored is None:
            return False
        profiles = [
            (str(p["id"]), str(p["name"])) for p in await list_exposed_profiles(conn, login)
        ]
    fingerprint = compute_agent_fingerprint(
        agent_rows=agent_rows,
        profiles=profiles,
        mcp_url=mcp_url,
        project_root=project_root,
        ws_name=ws_name,
        owner=login,
        ws_id=ws_id,
    )
    return fingerprint == stored


async def resync_owner_workspaces(
    login: str, only_ws_ids: set[str] | None = None
) -> dict[str, list[str]]:
    """Resynchronise les workspaces à agents de l'utilisateur.

    only_ws_ids : restreint aux ws_id donnés (ex. ceux affectés par un décochage) ;
    None = tous les workspaces du spec qui déclarent des agents.
    """
    results: dict[str, list[str]] = {"synced": [], "unchanged": [], "skipped": [], "failed": []}
    user_cfg = await load_user(login)
    global_cfg = load_global()
    mcp_url = global_cfg.server.external_url.rstrip("/") + "/mcp/"

    for spec in user_cfg.workspaces:
        ws_id = f"{login}-{spec.name}"
        if not spec.agents or (only_ws_ids is not None and ws_id not in only_ws_ids):
            continue
        project_root = f"/workspaces/{ws_id}"
        try:
            if not _host_supported(spec, global_cfg):
                results["skipped"].append(ws_id)
                _log.warning("agent_resync_skipped_host", ws_id=ws_id, host=spec.host)
                continue
            if not await _ws_running(ws_id):
                results["skipped"].append(ws_id)
                _log.info("agent_resync_skipped_stopped", ws_id=ws_id)
                continue
            # Idempotence : config inchangée → pas de rotation ni de réécriture
            # (sinon l'agent en cours perd sa clef et doit se ré-authentifier).
            if await _config_unchanged(
                login=login,
                ws_id=ws_id,
                agents=list(spec.agents),
                mcp_url=mcp_url,
                ws_name=spec.name,
                project_root=project_root,
            ):
                results["unchanged"].append(ws_id)
                _log.info("agent_resync_unchanged", ws_id=ws_id)
                continue
            await push_agent_files(
                login=login,
                ws_id=ws_id,
                ws_name=spec.name,
                agents=list(spec.agents),
                mcp_url=mcp_url,
                project_root=project_root,
            )
            results["synced"].append(ws_id)
        except Exception as exc:
            results["failed"].append(ws_id)
            _log.warning(
                "agent_resync_failed", ws_id=ws_id, error=type(exc).__name__, exc_info=True
            )
    _log.info("agent_resync_done", login=login, **{k: len(v) for k, v in results.items()})
    return results


async def resync_agent_type_workspaces(agent_id: str) -> dict[str, list[str]]:
    """Resynchronise tous les workspaces (tous utilisateurs) qui référencent ce
    type d'agent — déclenché après l'édition du template/filename."""
    from sqlalchemy import select

    from ..db.engine import _get_engine
    from ..db.tables import users

    async with _get_engine().connect() as conn:
        logins = [r[0] for r in (await conn.execute(select(users.c.login))).all()]

    merged: dict[str, list[str]] = {"synced": [], "skipped": [], "failed": []}
    for login in logins:
        user_cfg = await load_user(login)
        targets = {
            f"{login}-{spec.name}" for spec in user_cfg.workspaces if agent_id in spec.agents
        }
        if not targets:
            continue
        results = await resync_owner_workspaces(login, only_ws_ids=targets)
        for key, values in results.items():
            merged[key].extend(values)
    return merged


async def reconcile_agents_on_boot(throttle_s: float = 5.0) -> None:
    """Réconciliation au démarrage du portail (spec 35b, déclencheur 4).

    Les conteneurs restés running pendant une indisponibilité du portail peuvent
    porter une config agents périmée (profil décoché, template édité). Best-effort
    et throttlée : ne lève jamais, n'empêche pas le boot.
    """
    try:
        running = await _list_running()
    except Exception:
        _log.warning("agent_boot_reconcile_list_failed", exc_info=True)
        return

    by_login: dict[str, set[str]] = {}
    for row in running:
        by_login.setdefault(str(row["login"]), set()).add(str(row["ws_id"]))

    for login, ws_ids in by_login.items():
        try:
            user_cfg = await load_user(login)
        except Exception:
            _log.warning("agent_boot_reconcile_user_failed", login=login, exc_info=True)
            continue
        targets = {
            f"{login}-{spec.name}"
            for spec in user_cfg.workspaces
            if spec.agents and f"{login}-{spec.name}" in ws_ids
        }
        if not targets:
            continue
        try:
            await resync_owner_workspaces(login, only_ws_ids=targets)
        except Exception:
            _log.warning("agent_boot_reconcile_failed", login=login, exc_info=True)
        if throttle_s:
            await asyncio.sleep(throttle_s)
