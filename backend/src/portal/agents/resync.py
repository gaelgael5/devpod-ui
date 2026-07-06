"""Resync à chaud des fichiers agent-config (spec 35 §3).

Déclenché après commit par les routes ((dé)cochage « exposé aux workspaces »,
édition d'un type d'agent) : pour chaque workspace concerné, rotation des clefs
+ régénération + push. Le bind mount rend la mise à jour visible dans les
conteneurs sans reprovisionner.

Best-effort par workspace : un échec (host injoignable, agent stale) est loggé
et n'empêche pas les autres — les clefs révoquées côté DB restent le fail-closed.
"""

from __future__ import annotations

import structlog

from ..config.models import GlobalConfig, WorkspaceSpec
from ..config.store import load_global, load_user

_log = structlog.get_logger(__name__)


def _ssh_params(spec: WorkspaceSpec, global_cfg: GlobalConfig) -> tuple[str, str, str] | None:
    """(ssh_user, ssh_host, host_cert_slug) si le host du spec est un SSH prêt."""
    from ..devpod.env import _find_host

    host_cfg = _find_host(spec.host, global_cfg)
    if host_cfg.type != "ssh" or not (host_cfg.address and host_cfg.host_cert_slug):
        return None
    ssh_user, ssh_host = "root", host_cfg.address
    if "@" in host_cfg.address:
        ssh_user, ssh_host = host_cfg.address.split("@", 1)
    return ssh_user, ssh_host, host_cfg.host_cert_slug


async def resync_owner_workspaces(
    login: str, only_ws_ids: set[str] | None = None
) -> dict[str, list[str]]:
    """Resynchronise les workspaces à agents de l'utilisateur.

    only_ws_ids : restreint aux ws_id donnés (ex. ceux affectés par un décochage) ;
    None = tous les workspaces du spec qui déclarent des agents.
    """
    from ..devpod.service import _materialize_system_cert
    from .provisioning import _load_requested_agent_types, sync_agent_config

    results: dict[str, list[str]] = {"synced": [], "skipped": [], "failed": []}
    user_cfg = await load_user(login)
    global_cfg = load_global()
    mcp_url = global_cfg.server.external_url.rstrip("/") + "/mcp/"

    for spec in user_cfg.workspaces:
        ws_id = f"{login}-{spec.name}"
        if not spec.agents or (only_ws_ids is not None and ws_id not in only_ws_ids):
            continue
        try:
            ssh = _ssh_params(spec, global_cfg)
            if ssh is None:
                results["skipped"].append(ws_id)
                _log.warning("agent_resync_skipped_host", ws_id=ws_id, host=spec.host)
                continue
            ssh_user, ssh_host, cert_slug = ssh
            key_path = await _materialize_system_cert(cert_slug, login)
            agent_rows = await _load_requested_agent_types(spec.agents)
            await sync_agent_config(
                login=login,
                ws_id=ws_id,
                ws_name=spec.name,
                agent_rows=agent_rows,
                ssh_user=ssh_user,
                ssh_host=ssh_host,
                ssh_key_path=key_path,
                mcp_url=mcp_url,
                project_root=f"/workspaces/{ws_id}",
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
