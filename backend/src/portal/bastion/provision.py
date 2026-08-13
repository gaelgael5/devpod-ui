"""Provisioning Termix « Modèle B » — appelé par les AUTOMATES (spec 18 T5).

Les events `workspace.*` déclenchent des automates qui appellent
`POST /admin/service/bastion/provision` / `deprovision`. Erreurs PROPAGÉES : le
run de l'automate les trace (historique, rejeu).

Modèle B : Termix se connecte EN DIRECT au sshd du workspace, publié sur
`node_ip:ssh_port` (spec 18 T1), en `ws_user` (image_user du profil, défaut
vscode) avec la clé du workspace. Fan-out multi-instance : le host est déclaré sur
CHAQUE instance Termix de l'union des instances des users qui y ont accès
(propriétaire + `user_host_grant`), et partagé per-user (`type:"user"`, id trouvé
par `sub`) sur chacune. Un compte Termix pas encore créé (1er login) est mis « en
attente » → l'automate rejoue (idempotent).

État par workspace = secret système `ws-bastion-<ws_id>` (JSON chiffré) :
`{login, key, instances: {instance_id: {host_id, cred_id, ip, port, user}}}`.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from ..config.store import load_global
from ..db import termix_instance as ti
from ..db import user_host_grant as uhg
from ..db import user_termix_instance as uti
from ..db.engine import _get_engine
from ..db.user_config import get_workspace_profile_ref_db, owner_identity_subject
from ..db.workspace_status import get_status_db, list_ssh_hosts_db
from ..devpod.env import _find_host
from ..profiles.repository import ProfileError
from ..secrets import system as sysec
from . import keys as bkeys
from .termix_client import TermixClient

_log = structlog.get_logger(__name__)


class BastionNotConfiguredError(RuntimeError):
    """Provisioning Termix désactivé (toggle Admin → Bastion Termix)."""


def _slug(ws_id: str) -> str:
    return f"ws-bastion-{ws_id}"


# Mot de passe d'INITIALISATION des comptes Termix créés à l'association (spec 18
# T5). L'utilisateur le change / merge son OIDC ensuite. NE PAS considérer comme un
# secret durable — à durcir avant prod (mdp aléatoire stocké, ou forçage au 1er login).
_INIT_PASSWORD = "1234"


def enabled() -> bool:
    """True si le provisioning Termix est activé (toggle maître)."""
    return bool(load_global().bastion.enabled)


def _require_enabled() -> None:
    if not enabled():
        raise BastionNotConfiguredError(
            "provisioning Termix désactivé (Admin → Bastion Termix : activer)"
        )


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


async def ensure_ws_ssh_pubkey(login: str, ws_id: str) -> str:
    """Clé SSH ed25519 du workspace (idempotent) → clé publique.

    Spec 18 T1 : générée par le portail AU `up`, avant le build, pour que le
    composant `ssh-access` pose la pubkey dans `authorized_keys` du conteneur. La
    clé privée est stockée dans le secret `ws-bastion-<ws_id>` (réutilisé par le
    provisioning Termix). Rejouable : ré-appel = même clé. Préserve `instances`.
    """
    state = await _load_state(ws_id)
    if state and state.get("key"):
        return bkeys.public_from_private(str(state["key"]), f"ws:{ws_id}")
    private, public = bkeys.generate_keypair(comment=f"ws:{ws_id}")
    await _save_state(ws_id, {**(state or {}), "login": login, "key": private})
    return public


# ─── Résolution des cibles Modèle B ─────────────────────────────────────────────


async def _resolve_ws_user(login: str, ws_id: str, conn: Any) -> str:
    """Utilisateur SSH du workspace = image_user du profil, sinon 'vscode'."""
    name = ws_id[len(login) + 1 :] if ws_id.startswith(f"{login}-") else ws_id
    ref = await get_workspace_profile_ref_db(login, name, conn)
    if ref is None or ref[0] not in ("shared", "user"):
        return "vscode"
    from typing import Literal, cast

    from ..db.profiles import AsyncProfileRepository

    try:
        profile = await AsyncProfileRepository().get(
            cast("Literal['shared', 'user']", ref[0]), ref[1], login
        )
    except ProfileError:
        return "vscode"
    return profile.image_user or "vscode"


def _node_ip(host_name: str) -> str:
    """IP LAN joignable du node depuis son nom (strip d'un éventuel user@)."""
    host_cfg = _find_host(host_name, load_global())
    addr = (host_cfg.address or "").strip()
    if not addr:
        raise RuntimeError(f"node {host_name!r} sans adresse (host.address vide)")
    return addr.split("@", 1)[1] if "@" in addr else addr


async def _target(login: str, ws_id: str, conn: Any) -> tuple[str, int, str]:
    """(node_ip, ssh_port, ws_user) du host Modèle B. Lève si non publié."""
    status = await get_status_db(ws_id, conn)
    if status is None:
        raise RuntimeError(f"workspace {ws_id!r} inconnu (workspace_status absent)")
    ssh_port = status.get("ssh_port")
    host_name = status.get("host_name")
    if not ssh_port or not host_name:
        raise RuntimeError(
            f"workspace {ws_id!r} sans host SSH publié (ssh_port/host_name manquant)"
        )
    return _node_ip(str(host_name)), int(ssh_port), await _resolve_ws_user(login, ws_id, conn)


async def _apikey(apikey_secret: str, conn: Any) -> str:
    return await sysec.reveal_system_secret(apikey_secret, conn)


async def _accessors(login: str, ws_id: str, conn: Any) -> list[str]:
    """Logins ayant accès au host : propriétaire + grants (spec 18 T3)."""
    granted = await uhg.list_users_for_host(conn, ws_id)
    return sorted(set(granted) | {login})


async def ensure_termix_account(conn: Any, login: str, instance_ids: list[str]) -> list[str]:
    """Crée (idempotent) le compte Termix LOCAL du user (`username = email`) sur
    chaque instance donnée — appelé à l'association user↔instance (spec 18 T5).

    Le login Termix se fait par email ; le compte est créé avec le mot de passe
    d'initialisation `_INIT_PASSWORD` (l'user le change / merge son OIDC ensuite,
    pas d'API de merge). Best-effort : retourne la liste des erreurs
    (`instance: message`) sans lever, pour ne pas bloquer l'association en base.
    """
    email = (await owner_identity_subject(login)).get("email")
    if not email:
        _log.warning("termix_account_no_email", login=login)
        return [f"{login} : email manquant (compte Termix non créé)"]
    errors: list[str] = []
    for inst_id in instance_ids:
        inst = await ti.get(conn, inst_id)
        if inst is None:
            continue
        try:
            apikey = await _apikey(inst["apikey_secret"], conn)
            async with TermixClient(inst["url"], apikey) as tx:
                created = await tx.create_user(email, _INIT_PASSWORD)
            _log.info(
                "termix_account_ensured",
                login=login,
                email=email,
                instance=inst.get("name"),
                created=created,
            )
        except Exception as exc:  # best-effort : l'association en base reste valable
            _log.warning(
                "termix_account_failed", login=login, instance=inst.get("name"), error=str(exc)
            )
            errors.append(f"{inst.get('name', inst_id)} : {exc}")
    return errors


# ─── Provision / deprovision ────────────────────────────────────────────────────


async def _ensure_host_on_instance(
    tx: TermixClient,
    ws_id: str,
    private: str,
    ip: str,
    port: int,
    user: str,
    prev: dict[str, Any] | None,
) -> dict[str, Any]:
    """Crée (ou recrée si cible changée / host perdu) credential + host. → rec état."""
    if prev is not None:
        same = prev.get("ip") == ip and prev.get("port") == port and prev.get("user") == user
        known = await tx.list_host_ids()
        host_id = prev.get("host_id")
        if same and host_id is not None and (known is None or int(host_id) in known):
            return prev
        # Cible changée ou host perdu : purge l'ancien puis recrée.
        if host_id is not None:
            await tx.delete_host(int(host_id))
        if prev.get("cred_id"):
            await tx.delete_credential(int(prev["cred_id"]))
    cred_id = await tx.create_credential(_slug(ws_id), user, private)
    if cred_id is None:
        raise RuntimeError("Termix POST /credentials : réponse sans id exploitable")
    host_id = await tx.create_host(ws_id, ip, port, user, cred_id)
    if host_id is None:
        raise RuntimeError("Termix POST /host : réponse sans id exploitable")
    return {"host_id": host_id, "cred_id": cred_id, "ip": ip, "port": port, "user": user}


async def provision_workspace(login: str, ws_id: str) -> dict[str, Any]:
    """Provisionne (idempotent) l'accès Termix d'un workspace, en fan-out. Erreurs
    propagées. `created` liste les instances (re)provisionnées ; `pending` liste les
    users dont le compte Termix n'existe pas encore (→ rejeu de l'automate)."""
    _require_enabled()
    state = await _load_state(ws_id)
    private = str(state["key"]) if state and state.get("key") else None
    if private is None:
        private, _ = bkeys.generate_keypair(comment=f"ws:{ws_id}")
    prev_instances: dict[str, Any] = dict((state or {}).get("instances", {}))

    async with _get_engine().connect() as conn:
        ip, port, ws_user = await _target(login, ws_id, conn)
        accessors = await _accessors(login, ws_id, conn)
        # login → (instances, sub) ; union des instances → dict id→instance.
        per_user_instances: dict[str, set[str]] = {}
        emails: dict[str, str | None] = {}
        union: dict[str, dict[str, Any]] = {}
        for lg in accessors:
            insts = await uti.resolve_instances_for_user(conn, lg)
            per_user_instances[lg] = {i["id"] for i in insts}
            for i in insts:
                union[i["id"]] = i
            emails[lg] = (await owner_identity_subject(lg)).get("email")

    new_instances: dict[str, Any] = {}
    pending: list[str] = []
    for inst_id, inst in union.items():
        async with _get_engine().connect() as conn:
            apikey = await _apikey(inst["apikey_secret"], conn)
        async with TermixClient(inst["url"], apikey) as tx:
            rec = await _ensure_host_on_instance(
                tx, ws_id, private, ip, port, ws_user, prev_instances.get(inst_id)
            )
            new_instances[inst_id] = rec
            for lg in accessors:
                if inst_id not in per_user_instances[lg]:
                    continue
                email = emails.get(lg)
                if not email:
                    # Sans email → non partageable (login Termix = email, spec 18 T5).
                    _log.warning("bastion_share_no_email", login=lg, ws_id=ws_id)
                    continue
                uid = await tx.find_user_id(email)
                _log.info(
                    "bastion_share_lookup",
                    login=lg,
                    email=email,
                    found=uid,
                    instance=inst.get("name"),
                )
                if uid is None:
                    pending.append(f"{lg}@{inst.get('name', inst_id)}")
                    continue
                await tx.share_host_to_user(int(rec["host_id"]), uid)

    await _save_state(ws_id, {"login": login, "key": private, "instances": new_instances})
    _log.info(
        "bastion_provisioned",
        ws_id=ws_id,
        instances=list(new_instances),
        pending=pending,
    )
    # `pending` = comptes Termix pas encore créés (partage différé) : on NE lève PAS
    # (sinon 502) — les comptes sont normalement créés à l'association ; on remonte
    # simplement l'info. Un re-provision les rattrapera.
    if pending:
        _log.warning("bastion_share_pending", ws_id=ws_id, pending=pending)
    return {"ws_id": ws_id, "instances": list(new_instances), "created": True, "pending": pending}


async def provision_user_access(conn: Any, login: str) -> list[str]:
    """(Ré)partage à `login`, sur ses instances, tous les hosts SSH auxquels il a
    accès — appelé à l'association user↔instance (spec 18 T5) pour que « associer »
    suffise (plus besoin d'attendre un event workspace).

    Accès = workspaces publiés dont il est propriétaire + hosts accordés (T3). Pour
    chaque, on rejoue `provision_workspace(owner, ws_id)` (idempotent, fan-out sur
    toutes les instances des accessors). Best-effort → liste d'avertissements.
    """
    if not enabled():
        return []
    owned = [h["ws_id"] for h in await list_ssh_hosts_db(conn) if h.get("login") == login]
    granted = await uhg.list_hosts_for_user(conn, login)
    warnings: list[str] = []
    for ws_id in sorted(set(owned) | set(granted)):
        status = await get_status_db(ws_id, conn)
        owner = (status or {}).get("login") or login
        try:
            res = await provision_workspace(str(owner), ws_id)
            if res.get("pending"):
                warnings.append(f"{ws_id} : partage en attente {res['pending']}")
        except Exception as exc:  # best-effort : n'annule pas l'association
            _log.warning("provision_user_access_failed", login=login, ws_id=ws_id, error=str(exc))
            warnings.append(f"{ws_id} : {exc}")
    return warnings


async def deprovision_workspace(login: str, ws_id: str) -> dict[str, Any]:
    """Retire host + credential Termix sur toutes les instances + l'état. Erreurs
    propagées ; 404 de suppression tolérés (rejeu idempotent)."""
    _require_enabled()
    state = await _load_state(ws_id)
    if state is None:
        return {"ws_id": ws_id, "termix_deleted": False, "instances": []}
    instances: dict[str, Any] = dict(state.get("instances", {}))
    deleted: list[str] = []
    for inst_id, rec in instances.items():
        async with _get_engine().connect() as conn:
            inst = await ti.get(conn, inst_id)
            if inst is None:
                continue
            apikey = await _apikey(inst["apikey_secret"], conn)
        async with TermixClient(inst["url"], apikey) as tx:
            if rec.get("host_id"):
                await tx.delete_host(int(rec["host_id"]))
            if rec.get("cred_id"):
                await tx.delete_credential(int(rec["cred_id"]))
        deleted.append(inst_id)
    async with _get_engine().begin() as conn:
        await sysec.delete_system_secret(_slug(ws_id), conn)
    _log.info("bastion_deprovisioned", ws_id=ws_id, instances=deleted)
    return {"ws_id": ws_id, "termix_deleted": True, "instances": deleted}
