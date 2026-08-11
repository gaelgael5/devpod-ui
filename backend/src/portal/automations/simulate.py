"""Simulation & rattrapage (comme docflow) : injection d'event de test + backfill.

- `inject_test_event` : appende un event synthétique (host / workspace / session
  « a bougé ») au journal, sans clé de dédup → toujours ré-exécuté (test du runner).
- `backfill` : émet, pour chaque host / workspace / session EXISTANT, un event de
  synchro avec une clé de dédup stable → première synchro + réconciliation
  idempotentes (rejouer le backfill ne spamme pas de nouveaux appels).
"""

from __future__ import annotations

import structlog

from ..db.user_config import owner_identity_subject
from ..events.bus import emit_event

_log = structlog.get_logger(__name__)


async def inject_test_event(
    kind: str,
    *,
    actor: str,
    workspace: str | None = None,
    host_name: str | None = None,
    session: str | None = None,
) -> dict[str, str]:
    """Injecte un event synthétique de test (déclenche le runner comme une vraie mutation)."""
    ws = workspace or "test-ws"
    if kind == "user":
        await emit_event(
            "user.refreshed",
            actor=actor,
            subject={
                "login": actor,
                "sub": f"test-sub-{actor}",
                "email": f"{actor}@example.org",
                "identity": "",
            },
        )
        return {"emitted": "user.refreshed"}
    if kind == "host":
        name = host_name or "test-host"
        await emit_event(
            "test_server.updated",
            actor=actor,
            workspace=ws,
            subject={
                "host_name": name,
                "alias": name,
                "address": "root@203.0.113.10",
                "password_changed": False,
            },
        )
        return {"emitted": "test_server.updated"}
    if kind == "workspace":
        await emit_event(
            "workspace.updated",
            actor=actor,
            workspace=ws,
            subject={
                **await owner_identity_subject(actor),
                "ws_id": f"{actor}-{ws}",
                "node": None,
                "address": None,
                "status": "running",
            },
        )
        return {"emitted": "workspace.updated"}
    if kind == "session":
        await emit_event(
            "session.created",
            actor=actor,
            workspace=ws,
            subject={"session": session or "test-session", "start_recipe": None},
        )
        return {"emitted": "session.created"}
    raise ValueError(f"kind d'injection inconnu : {kind!r}")


async def backfill(*, actor: str) -> dict[str, int]:
    """Émet un event de synchro par host / workspace / session existant (idempotent)."""
    from sqlalchemy import select

    from ..config.store import load_global
    from ..db.engine import _get_engine
    from ..db.tables import users
    from ..db.test_hosts import list_all_test_hosts
    from ..db.workspace_status import list_running_db
    from ..sessions.aggregate import probe_workspace_sessions

    cfg = load_global()
    addr_by_host = {h.name: h.address for h in cfg.hosts}
    counts = {"users": 0, "hosts": 0, "workspaces": 0, "sessions": 0}

    async with _get_engine().connect() as conn:
        user_rows = (
            await conn.execute(
                select(users.c.login, users.c.sub, users.c.email, users.c.identity)
            )
        ).all()
        hosts = await list_all_test_hosts(conn)
        running = await list_running_db(conn)

    for login, sub, email, identity in user_rows:
        await emit_event(
            "user.refreshed",
            actor=login,
            subject={
                "login": login,
                "sub": sub or "",
                "email": email or "",
                "identity": identity or "",
            },
            dedup_key=f"backfill:user:{login}",
        )
        counts["users"] += 1

    for _login, ws_name, host_name, alias in hosts:
        await emit_event(
            "test_server.updated",
            actor=actor,
            workspace=ws_name,
            subject={
                "host_name": host_name,
                "alias": alias or host_name,
                "address": addr_by_host.get(host_name, ""),
                "password_changed": False,
            },
            dedup_key=f"backfill:host:{host_name}",
        )
        counts["hosts"] += 1

    for row in running:
        ws_id = row.get("ws_id") or ""
        login = row.get("login") or ""
        if not ws_id:
            continue
        ws_name = ws_id.removeprefix(f"{login}-")
        await emit_event(
            "workspace.updated",
            actor=actor,
            workspace=ws_name,
            subject={
                **await owner_identity_subject(login),
                "ws_id": ws_id,
                "node": row.get("host_name"),
                "address": row.get("hostname"),
                "status": row.get("status"),
            },
            dedup_key=f"backfill:ws:{ws_id}",
        )
        counts["workspaces"] += 1

    for row in running:
        ws_id = row.get("ws_id") or ""
        login = row.get("login") or ""
        if not ws_id or not login:
            continue
        try:
            rc, sessions = await probe_workspace_sessions(login, ws_id)
        except Exception:
            _log.warning("backfill_session_probe_failed", ws_id=ws_id, exc_info=True)
            continue
        if rc != 0:
            continue
        ws_name = ws_id.removeprefix(f"{login}-")
        for s in sessions:
            await emit_event(
                "session.created",
                actor=actor,
                workspace=ws_name,
                subject={"session": s, "start_recipe": None},
                dedup_key=f"backfill:session:{ws_id}:{s}",
            )
            counts["sessions"] += 1

    _log.info("automation_backfill_done", actor=actor, **counts)
    return counts
