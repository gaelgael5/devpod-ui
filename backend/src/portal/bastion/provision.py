"""Provisioning bastion↔Termix au cycle de vie d'un workspace.

À la création : génère (une fois) la clé du workspace, pose la clé publique dans
`authorized_keys` du bastion, et déclare côté Termix un credential (clé privée) +
un host (référence ce credential, vise l'IP:port du bastion) partagé au rôle
configuré. À la suppression : retire la ligne authorized_keys et supprime le host +
credential Termix. Best-effort : ne casse JAMAIS le cycle de vie du workspace.

État par workspace = un secret système `ws-bastion-<ws_id>` (JSON chiffré KEK :
clé privée + ids Termix) → idempotent et propre au nettoyage.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from ..config.store import load_global
from ..db.engine import _get_engine
from ..secrets import system as sysec
from . import keys as bkeys
from .authorized_keys import remove_entry, set_entry
from .termix_client import TermixClient

_log = structlog.get_logger(__name__)

# Utilisateur SSH de la connexion Termix → bastion (le ForceCommand relaie ensuite).
_SSH_USER = "root"


def _slug(ws_id: str) -> str:
    return f"ws-bastion-{ws_id}"


def enabled() -> bool:
    """True si la config Termix est complète (sinon provisioning inactif)."""
    b = load_global().bastion
    return bool(b.enabled and b.api_url and b.host and b.role)


async def _load_state(ws_id: str) -> dict[str, Any] | None:
    async with _get_engine().connect() as conn:
        try:
            raw = await sysec.reveal_system_secret(_slug(ws_id), conn)
        except KeyError:
            return None
    try:
        return dict(json.loads(raw))
    except (ValueError, TypeError):
        return None


async def _apikey() -> str:
    async with _get_engine().connect() as conn:
        return await sysec.reveal_system_secret(load_global().bastion.apikey_secret, conn)


async def _save_state(ws_id: str, state: dict[str, Any]) -> None:
    async with _get_engine().begin() as conn:
        await sysec.ensure_system_user(conn)
        await sysec.store_system_secret(
            slug=_slug(ws_id),
            label=f"bastion {ws_id}",
            value=json.dumps(state),
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )


async def provision_workspace(login: str, ws_id: str) -> None:
    """Idempotent. Best-effort : toute erreur est loguée, jamais propagée."""
    if not enabled():
        return
    try:
        state = await _load_state(ws_id)
        if state and state.get("key"):
            # Déjà provisionné : ré-assure seulement la ligne authorized_keys.
            await set_entry(login, ws_id, bkeys.public_from_private(state["key"], f"ws:{ws_id}"))
            return
        private, public = bkeys.generate_keypair(comment=f"ws:{ws_id}")
        await set_entry(login, ws_id, public)
        b = load_global().bastion
        apikey = await _apikey()
        host_id = cred_id = None
        async with TermixClient(b.api_url, apikey) as tx:
            cred_id = await tx.create_credential(_slug(ws_id), _SSH_USER, private)
            if cred_id is not None:
                host_id = await tx.create_host(
                    ws_id, b.host, b.port, _SSH_USER, cred_id
                )
            role_id = await tx.find_role_id(b.role)
            if host_id is not None and role_id is not None:
                await tx.share_host_to_role(host_id, role_id)
        await _save_state(
            ws_id, {"login": login, "key": private, "host_id": host_id, "cred_id": cred_id}
        )
        _log.info("bastion_provisioned", ws_id=ws_id, host_id=host_id, role=b.role)
    except Exception:
        _log.warning("bastion_provision_failed", login=login, ws_id=ws_id, exc_info=True)


_SLUG_PREFIX = "ws-bastion-"


def _orphan_ws_ids(valid: set[str], slugs: list[str]) -> list[str]:
    """ws_id provisionnés (slugs `ws-bastion-*`) absents de `valid` = orphelins."""
    out: list[str] = []
    for slug in slugs:
        if slug.startswith(_SLUG_PREFIX):
            ws_id = slug[len(_SLUG_PREFIX) :]
            if ws_id not in valid:
                out.append(ws_id)
    return out


async def reconcile_orphans() -> int:
    """Supprime le provisioning bastion des workspaces qui n'existent plus.

    Source de vérité = `workspace_status` (purgée à la suppression d'un workspace).
    Un état bastion `ws-bastion-<ws_id>` sans ligne workspace_status = orphelin
    (workspace supprimé pendant que le portail était down, ou provisioning résiduel).
    Best-effort. Retourne le nombre d'orphelins nettoyés.
    """
    if not enabled():
        return 0
    from sqlalchemy import select

    from ..db.tables import workspace_status

    try:
        async with _get_engine().connect() as conn:
            valid = {r[0] for r in (await conn.execute(select(workspace_status.c.ws_id))).all()}
            slugs = [s["slug"] for s in await sysec.list_system_secrets(conn)]
    except Exception:
        _log.warning("bastion_reconcile_read_failed", exc_info=True)
        return 0
    removed = 0
    for ws_id in _orphan_ws_ids(valid, slugs):
        state = await _load_state(ws_id)
        login = (state or {}).get("login") or ws_id.split("-", 1)[0]
        await deprovision_workspace(login, ws_id)
        removed += 1
    if removed:
        _log.info("bastion_orphans_reconciled", removed=removed)
    return removed


async def deprovision_workspace(login: str, ws_id: str) -> None:
    """Retire la ligne authorized_keys + supprime host/credential Termix. Best-effort."""
    if not enabled():
        return
    try:
        await remove_entry(login, ws_id)
        state = await _load_state(ws_id)
        if state:
            b = load_global().bastion
            apikey = await _apikey()
            async with TermixClient(b.api_url, apikey) as tx:
                if state.get("host_id"):
                    await tx.delete_host(int(state["host_id"]))
                if state.get("cred_id"):
                    await tx.delete_credential(int(state["cred_id"]))
            async with _get_engine().begin() as conn:
                await sysec.delete_system_secret(_slug(ws_id), conn)
        _log.info("bastion_deprovisioned", ws_id=ws_id)
    except Exception:
        _log.warning("bastion_deprovision_failed", login=login, ws_id=ws_id, exc_info=True)
