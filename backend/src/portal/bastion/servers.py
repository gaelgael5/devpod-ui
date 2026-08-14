"""Push des SERVEURS (hosts d'infra / ressources / tests) vers Termix par dossier.

Distinct des workspaces (provision.py) : ici la cible est une entrée `HostConfig`
(machine déclarée dans l'admin), connectée EN DIRECT par Termix via son sshd. Mapping
`usage` → dossier Termix, et destinataires selon la nature :

- `workspaces`/`portail`     → dossier ``hosts`` → **admins** ;
- `autres`                   → dossier ``Others`` → **admins** ;
- `ressources`               → dossier ``Ressources`` → **admins** ;
- `tests`                    → dossier ``workspaces`` → **propriétaire** du workspace
  qui a créé la VM (lien `workspace_test_hosts`).

Réutilise le cœur de `provision.py` : possession du host sur le **compte OIDC** de
chaque destinataire (`_ensure_host_owned_by_user`), dédup par nom, ré-appropriation.
Credential = clé SSH du host (`host_cert_slug`, cf. bootstrap-ssh admin) ; `ip`/`user`
extraits de `address` (``user@host``), port 22. Déclenché à chaque changement de host
(create/update/delete, cf. routes/admin). État par host = secret `srv-bastion-<name>` :
``{targets: {login: {instance_id: rec}}}``.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from ..config.store import load_global
from ..db import termix_instance as ti
from ..db import test_hosts
from ..db import user_termix_instance as uti
from ..db.engine import _get_engine
from ..db.user_config import is_admin_db, list_admin_logins, owner_identity_subject
from ..secrets import system as sysec
from ..secrets.system import reveal_system_cert
from .provision import (
    _apikey,
    _delete_named_as_owner,
    _ensure_account_copies,
    _try_link_accounts,
    enabled,
)
from .termix_client import TermixClient

_log = structlog.get_logger(__name__)

# usage HostConfig → dossier Termix (None = non poussé). `autres` a son propre
# dossier « Others » (comme la section « Autres serveurs » de l'écran hosts) ; le
# changement de dossier est appliqué au prochain sync (folder comparé dans le rec).
_USAGE_FOLDER: dict[str, str] = {
    "workspaces": "hosts",
    "portail": "hosts",
    "autres": "Others",
    "ressources": "Ressources",
    "tests": "workspaces",
}
_SSH_PORT = 22


def _srv_slug(host_name: str) -> str:
    return f"srv-bastion-{host_name}"


def _ssh_target(address: str) -> tuple[str, str]:
    """`address` (``user@host``) → (host, ssh_user). Défaut user=root."""
    user, sep, host = address.partition("@")
    if not sep:
        return address, "root"
    return host, user or "root"


async def _load_srv_state(host_name: str) -> dict[str, Any] | None:
    async with _get_engine().connect() as conn:
        try:
            raw = await sysec.reveal_system_secret(_srv_slug(host_name), conn)
        except KeyError:
            return None
    try:
        return dict(json.loads(raw))
    except (ValueError, TypeError):
        return None


async def _save_srv_state(host_name: str, state: dict[str, Any]) -> None:
    async with _get_engine().begin() as conn:
        await sysec.ensure_system_user(conn)
        await sysec.store_system_secret(
            slug=_srv_slug(host_name),
            label=f"bastion serveur {host_name}",
            value=json.dumps(state),
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )


async def _delete_srv_state(host_name: str) -> None:
    async with _get_engine().begin() as conn:
        await sysec.delete_system_secret(_srv_slug(host_name), conn)


async def _resolve_targets(
    host: Any, conn: Any
) -> list[tuple[str, str | None, list[dict[str, Any]]]]:
    """Destinataires (login, email, instances Termix) selon l'usage du host."""
    if host.usage == "tests":
        owner = await test_hosts.owner_of_test_host(host.name, conn)
        logins = [owner[0]] if owner else []
    else:  # hosts d'infra / ressources → admins
        logins = await list_admin_logins(conn)
    out: list[tuple[str, str | None, list[dict[str, Any]]]] = []
    for login in logins:
        email = (await owner_identity_subject(login)).get("email")
        instances = await uti.resolve_instances_for_user(conn, login)
        out.append((login, email, instances))
    return out


def _rec_map(value: Any) -> dict[str, Any]:
    """Normalise une entrée d'état en map {uid: rec} (ancien format à plat → {} )."""
    if isinstance(value, dict) and "host_id" not in value:
        return {k: v for k, v in value.items() if isinstance(v, dict)}
    return {}


async def _delete_server_map(host_name: str, inst_id: str, rec_map: dict[str, Any]) -> None:
    """Supprime les copies d'un (login, instance) EN TANT QUE chaque compte propriétaire."""
    if not rec_map:
        return
    async with _get_engine().connect() as conn:
        inst = await ti.get(conn, inst_id)
        if inst is None:
            return
        apikey = await _apikey(inst["apikey_secret"], conn)
    async with TermixClient(inst["url"], apikey) as tx:
        for rec in rec_map.values():
            await _delete_named_as_owner(tx, inst, host_name, rec.get("owner"))


async def _cleanup_removed(
    prev_targets: dict[str, Any], new_targets: dict[str, Any], host_name: str
) -> None:
    """Supprime les copies des (login, instance) présents avant mais plus maintenant
    (admin qui a perdu le rôle, instance retirée, usage changé)."""
    for login, insts in prev_targets.items():
        kept = new_targets.get(login, {})
        for inst_id, rec_map in insts.items():
            if inst_id not in kept:
                await _delete_server_map(host_name, inst_id, _rec_map(rec_map))


async def sync_server_host(host_name: str) -> None:
    """(Ré)pousse un serveur vers Termix pour ses destinataires (idempotent, best-effort).

    Host absent / type non-ssh / usage non mappé / sans clé SSH → déprovisionne l'état.
    Déclenché à chaque changement de host."""
    if not enabled():
        return
    host = next((h for h in load_global().hosts if h.name == host_name), None)
    folder = _USAGE_FOLDER.get(host.usage) if host is not None else None
    if host is None or host.type != "ssh" or folder is None or not host.host_cert_slug:
        await deprovision_server_host(host_name)
        return
    ip, ssh_user = _ssh_target(host.address)
    async with _get_engine().connect() as conn:
        try:
            private = await reveal_system_cert(host.host_cert_slug, conn)
        except KeyError:
            _log.warning("srv_host_no_cert", host=host_name, slug=host.host_cert_slug)
            await deprovision_server_host(host_name)
            return
        targets = await _resolve_targets(host, conn)

    state = await _load_srv_state(host_name)
    prev_targets: dict[str, Any] = dict((state or {}).get("targets", {}))
    new_targets: dict[str, Any] = {}
    for login, email, instances in targets:
        per_inst: dict[str, Any] = {}
        for inst in instances:
            async with _get_engine().connect() as conn:
                apikey = await _apikey(inst["apikey_secret"], conn)
            async with TermixClient(inst["url"], apikey) as tx:
                prev_map = _rec_map(prev_targets.get(login, {}).get(inst["id"]))
                # Une copie par compte (interne + OIDC) de l'email — chaque compte alimenté.
                copies = await _ensure_account_copies(
                    tx, inst, host_name, email, private, ip, _SSH_PORT, ssh_user, prev_map, folder
                )
                # Nettoie les copies des comptes disparus sur cette instance.
                for uid, rec in prev_map.items():
                    if uid not in copies:
                        await _delete_named_as_owner(tx, inst, host_name, rec.get("owner"))
                await _try_link_accounts(tx, email)  # fusion interne↔OIDC best-effort
                per_inst[inst["id"]] = copies
        new_targets[login] = per_inst

    await _cleanup_removed(prev_targets, new_targets, host_name)
    await _save_srv_state(host_name, {"targets": new_targets})
    _log.info("srv_host_synced", host=host_name, folder=folder, targets=list(new_targets))


async def sync_server_hosts_for_user(login: str) -> None:
    """Pousse à `login` les serveurs qu'il doit voir — appelé à l'association Termix
    (pour que « (ré)associer » suffise, sans attendre un changement de host).

    Admin → tous les hosts d'infra + ressources ; plus les serveurs de TEST qu'il a
    créés. Chaque host concerné est re-synchronisé (idempotent, fan-out sur tous ses
    destinataires). Ouvre sa propre connexion (BackgroundTask après commit de
    l'association → instances à jour). Best-effort."""
    if not enabled():
        return
    async with _get_engine().connect() as conn:
        admin = await is_admin_db(login, conn)
        names: set[str] = set()
        for host in load_global().hosts:
            if host.type != "ssh" or not host.host_cert_slug:
                continue
            if _USAGE_FOLDER.get(host.usage) is None:
                continue
            if host.usage == "tests":
                owner = await test_hosts.owner_of_test_host(host.name, conn)
                if owner and owner[0] == login:
                    names.add(host.name)
            elif admin:
                names.add(host.name)
    for name in sorted(names):
        await sync_server_host(name)
    _log.info("srv_hosts_synced_for_user", login=login, admin=admin, hosts=sorted(names))


async def try_link_accounts_for_user(login: str) -> None:
    """Tente de fusionner les comptes Termix (interne↔OIDC) de `login` sur chacune de
    ses instances — best-effort, appelé à chaque login (spec 18). Silencieux/idempotent."""
    if not enabled():
        return
    async with _get_engine().connect() as conn:
        email = (await owner_identity_subject(login)).get("email")
        instances = await uti.resolve_instances_for_user(conn, login)
    if not email:
        return
    for inst in instances:
        try:
            async with _get_engine().connect() as conn:
                apikey = await _apikey(inst["apikey_secret"], conn)
            async with TermixClient(inst["url"], apikey) as tx:
                await _try_link_accounts(tx, email)
        except Exception as exc:
            _log.debug("termix_link_for_user_failed", login=login, error=str(exc))


async def deprovision_server_host(host_name: str) -> None:
    """Retire un serveur de Termix chez tous ses destinataires + purge l'état."""
    if not enabled():
        return
    state = await _load_srv_state(host_name)
    if state is None:
        return
    for _login, insts in dict(state.get("targets", {})).items():
        for inst_id, rec_map in insts.items():
            await _delete_server_map(host_name, inst_id, _rec_map(rec_map))
    await _delete_srv_state(host_name)
    _log.info("srv_host_deprovisioned", host=host_name)
