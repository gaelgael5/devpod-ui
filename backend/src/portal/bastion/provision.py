"""Provisioning bastion↔Termix — appelé par les AUTOMATES, plus par le lifecycle.

Les events `workspace.*` du journal durable `app_event` déclenchent des automates
qui appellent `POST /admin/service/bastion/provision` / `deprovision` (clé API
admin). Les erreurs sont PROPAGÉES : le run de l'automate les trace (historique,
rejeu depuis l'écran automates) — fini le best-effort silencieux.

À la provision : génère (une fois) la clé du workspace, pose la clé publique dans
`authorized_keys` du bastion, déclare côté Termix un credential (clé privée) + un
host (IP:port du bastion) et (re)partage le host au rôle configuré. Si Termix a
perdu le host (base réinitialisée), il est recréé. À la déprovision : retire la
ligne authorized_keys et supprime host + credential Termix (404 toléré).

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


class BastionNotConfiguredError(RuntimeError):
    """Config bastion incomplète : enabled + api_url + host + role sont requis."""


def _slug(ws_id: str) -> str:
    return f"ws-bastion-{ws_id}"


def enabled() -> bool:
    """True si la config Termix est complète (sinon provisioning inactif)."""
    b = load_global().bastion
    return bool(b.enabled and b.api_url and b.host and b.role)


def _require_enabled() -> Any:
    b = load_global().bastion
    if not (b.enabled and b.api_url and b.host and b.role):
        raise BastionNotConfiguredError(
            "bastion non configuré : enabled + api_url + host + role requis "
            "(Admin → Bastion Termix)"
        )
    return b


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


async def _create_and_share(tx: TermixClient, b: Any, ws_id: str, private: str) -> tuple[int, int]:
    """Crée credential + host et partage au rôle. Lève si Termix ne renvoie pas d'id."""
    cred_id = await tx.create_credential(_slug(ws_id), _SSH_USER, private)
    if cred_id is None:
        raise RuntimeError("Termix POST /credentials : réponse sans id exploitable")
    host_id = await tx.create_host(ws_id, b.host, b.port, _SSH_USER, cred_id)
    if host_id is None:
        raise RuntimeError("Termix POST /host : réponse sans id exploitable")
    await _share(tx, b, host_id)
    return host_id, cred_id


async def _share(tx: TermixClient, b: Any, host_id: int) -> None:
    role_id = await tx.find_role_id(b.role)
    if role_id is None:
        raise RuntimeError(f"rôle Termix {b.role!r} introuvable (à créer dans l'UI RBAC)")
    await tx.share_host_to_role(host_id, role_id)


async def provision_workspace(login: str, ws_id: str) -> dict[str, Any]:
    """Provisionne (idempotent) l'accès Termix d'un workspace. Erreurs propagées.

    État existant → ré-assure la ligne authorized_keys ET le partage au rôle ;
    si le host a disparu côté Termix (base perdue), credential + host sont recréés
    avec la même clé. `created` dit si des objets Termix ont été (re)créés.
    """
    b = _require_enabled()
    state = await _load_state(ws_id)
    apikey = await _apikey()
    private: str
    if state and state.get("key"):
        private = str(state["key"])
        await set_entry(login, ws_id, bkeys.public_from_private(private, f"ws:{ws_id}"))
        async with TermixClient(b.api_url, apikey) as tx:
            known = await tx.list_host_ids()
            host_id = state.get("host_id")
            if host_id is not None and (known is None or int(host_id) in known):
                # Host toujours là (ou vérification inconclusive) : re-partage seulement.
                await _share(tx, b, int(host_id))
                return {
                    "ws_id": ws_id,
                    "host_id": int(host_id),
                    "cred_id": state.get("cred_id"),
                    "created": False,
                }
            # Host perdu côté Termix : purge du credential résiduel puis recréation.
            if state.get("cred_id"):
                await tx.delete_credential(int(state["cred_id"]))
            new_host_id, cred_id = await _create_and_share(tx, b, ws_id, private)
    else:
        private, public = bkeys.generate_keypair(comment=f"ws:{ws_id}")
        await set_entry(login, ws_id, public)
        async with TermixClient(b.api_url, apikey) as tx:
            new_host_id, cred_id = await _create_and_share(tx, b, ws_id, private)
    await _save_state(
        ws_id, {"login": login, "key": private, "host_id": new_host_id, "cred_id": cred_id}
    )
    _log.info("bastion_provisioned", ws_id=ws_id, host_id=new_host_id, role=b.role)
    return {"ws_id": ws_id, "host_id": new_host_id, "cred_id": cred_id, "created": True}


async def deprovision_workspace(login: str, ws_id: str) -> dict[str, Any]:
    """Retire authorized_keys + host/credential Termix + l'état. Erreurs propagées.

    Idempotent : sans état connu c'est un no-op (la ligne authorized_keys est
    retirée quoi qu'il arrive) ; côté Termix les 404 de suppression sont tolérés.
    """
    _require_enabled()
    removed = await remove_entry(login, ws_id)
    state = await _load_state(ws_id)
    if state is None:
        return {"ws_id": ws_id, "removed": removed, "termix_deleted": False}
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
    return {"ws_id": ws_id, "removed": removed, "termix_deleted": True}
