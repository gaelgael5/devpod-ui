"""Provisioning Termix « Modèle B » — appelé DIRECTEMENT dans le lifecycle (spec 18 T5).

Pas d'automate (couplage assumé) : `up` → provision, `stop`/`delete` → deprovision
(cf. devpod/service.py). L'association user↔instance (routes/admin_users) crée le
compte Termix (username=email) + partage les hosts existants.

Modèle B : Termix se connecte EN DIRECT au sshd du workspace, publié sur
`node_ip:ssh_port` (spec 18 T1), en `ws_user` (image_user du profil, défaut vscode)
avec la clé du workspace. Fan-out multi-instance : le host est déclaré sur CHAQUE
instance Termix de l'union des instances des accessors (propriétaire +
`user_host_grant`). Le host est **possédé par le propriétaire** du workspace (créé
via une apikey éphémère mintée pour lui, pas par l'admin) puis **partagé aux autres
accessors** (identifiés par email). Compte Termix absent → « en attente » (pas de
502 ; un re-provision rattrape).

État par workspace = secret système `ws-bastion-<ws_id>` (JSON chiffré) :
`{login, key, instances: {instance_id: {host_id, cred_id, ip, port, user}}}`.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from datetime import UTC, datetime, timedelta
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


def _apikey_expiry() -> str:
    """Expiration courte (filet) des apikeys éphémères mintées pour un user."""
    return (datetime.now(UTC) + timedelta(minutes=10)).isoformat()


def _as_int(v: Any) -> int | None:
    """Id Termix → int (id host/credential est numérique) ; None sinon."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)
    return None


async def _delete_hosts_named(tx: TermixClient, ws_id: str) -> int:
    """Supprime TOUS les hosts (+ leur credential) dont le `name` == `ws_id`.

    Vu par `tx` (donc scopé au propriétaire de l'apikey). Nettoie les doublons /
    orphelins d'un delete non propagé. Retourne le nombre de hosts supprimés."""
    removed = 0
    for h in await tx.list_hosts():
        if h.get("name") != ws_id:
            continue
        hid = _as_int(h.get("id") if h.get("id") is not None else h.get("hostId"))
        if hid is not None:
            await tx.delete_host(hid)
            removed += 1
        cid = _as_int(h.get("credentialId") or h.get("credential_id"))
        if cid is not None:
            await tx.delete_credential(cid)
    return removed


async def _delete_ws_hosts_as_owner(
    admin_tx: TermixClient, inst: dict[str, Any], ws_id: str, owner_email: str | None
) -> int:
    """Supprime les hosts nommés `ws_id` sur l'instance EN TANT QUE le propriétaire.

    Les hosts sont possédés par le user (mint d'apikey éphémère au provisioning) :
    l'apikey admin ne les voit pas et ne peut pas les supprimer. On minte donc la
    clé du propriétaire, on supprime avec, puis on la jette. Fallback admin pour les
    hosts admin-owned (ancien comportement / provisioning en secours)."""
    owner_uid = await admin_tx.find_user_id(owner_email) if owner_email else None
    if owner_uid is not None:
        key_id, token = await admin_tx.create_apikey_for_user(
            owner_uid, f"portal-deprovision-{ws_id}", _apikey_expiry()
        )
        if token:
            try:
                async with TermixClient(inst["url"], token) as owner_tx:
                    return await _delete_hosts_named(owner_tx, ws_id)
            finally:
                if key_id:
                    try:
                        await admin_tx.delete_apikey(key_id)
                    except Exception:
                        _log.warning("termix_apikey_cleanup_failed", ws_id=ws_id, key_id=key_id)
    return await _delete_hosts_named(admin_tx, ws_id)


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
    # Idempotence par NOM : purge tout host résiduel du même ws_id (doublon /
    # orphelin d'un delete non propagé) AVANT d'en recréer un propre — sinon un
    # état vidé + host survivant = doublon (cas restart après stop KO).
    await _delete_hosts_named(tx, ws_id)
    # Nom de credential UNIQUE (suffixe GUID) : le nom n'est qu'un label (le suivi
    # se fait par cred_id), et un nom stable provoque des 409 « déjà existant » côté
    # Termix quand un credential résiduel traîne (recréation, delete non propagé,
    # double passe entre users). Spec 18 T5.
    cred_name = f"{_slug(ws_id)}-{uuid.uuid4().hex[:8]}"
    cred_id = await tx.create_credential(cred_name, user, private)
    if cred_id is None:
        raise RuntimeError("Termix POST /credentials : réponse sans id exploitable")
    host_id = await tx.create_host(ws_id, ip, port, user, cred_id)
    if host_id is None:
        raise RuntimeError("Termix POST /host : réponse sans id exploitable")
    return {"host_id": host_id, "cred_id": cred_id, "ip": ip, "port": port, "user": user}


async def _ensure_host_owned_by_user(
    admin_tx: TermixClient,
    inst: dict[str, Any],
    ws_id: str,
    owner_login: str,
    owner_email: str | None,
    private: str,
    ip: str,
    port: int,
    ws_user: str,
    prev: dict[str, Any] | None,
) -> dict[str, Any]:
    """Crée le host+credential POSSÉDÉ par le propriétaire du workspace.

    Mint une apikey éphémère pour lui (via l'apikey admin), crée avec son token, puis
    jette l'apikey. Fallback : si le proprio n'a pas de compte sur l'instance (pas
    d'email / user Termix absent), crée en admin (comportement historique) + log.
    """
    # No-op si la cible est inchangée : on fait confiance à l'état (host déjà créé,
    # même ip/port/user) pour NE PAS minter une apikey éphémère inutilement.
    if (
        prev is not None
        and prev.get("host_id")
        and prev.get("ip") == ip
        and prev.get("port") == port
        and prev.get("user") == ws_user
    ):
        return prev
    # Compte du propriétaire par username=email, SANS filtre is_oidc : après le link
    # OIDC (link-oidc-to-password), le compte fusionné devient is_oidc:true — filtrer
    # sur is_oidc=false le manquerait et ferait retomber en admin-owned (host invisible).
    owner_uid = await admin_tx.find_user_id(owner_email) if owner_email else None
    if owner_uid is not None:
        key_id, owner_token = await admin_tx.create_apikey_for_user(
            owner_uid, f"portal-provision-{ws_id}", _apikey_expiry()
        )
        if owner_token:
            try:
                async with TermixClient(inst["url"], owner_token) as owner_tx:
                    return await _ensure_host_on_instance(
                        owner_tx, ws_id, private, ip, port, ws_user, prev
                    )
            finally:
                if key_id:
                    try:
                        await admin_tx.delete_apikey(key_id)
                    except Exception:
                        _log.warning("termix_apikey_cleanup_failed", ws_id=ws_id, key_id=key_id)
    _log.warning(
        "bastion_host_admin_owned_fallback",
        ws_id=ws_id,
        instance=inst.get("name"),
        owner=owner_login,
    )
    return await _ensure_host_on_instance(admin_tx, ws_id, private, ip, port, ws_user, prev)


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
    # Diag (spec 18 T5) : pubkey mise dans le credential Termix — à comparer à
    # l'authorized_keys du conteneur (doivent être identiques, sinon auth KO).
    _log.info(
        "bastion_ws_pubkey", ws_id=ws_id, pubkey=bkeys.public_from_private(private, f"ws:{ws_id}")
    )

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
            # Host créé EN TANT QUE le propriétaire du workspace (owned by user, pas
            # admin) : apikey éphémère mintée pour lui, host+credential créés avec, puis
            # apikey jetée. Fallback admin si le proprio n'a pas de compte sur l'instance.
            rec = await _ensure_host_owned_by_user(
                tx,
                inst,
                ws_id,
                login,
                emails.get(login),
                private,
                ip,
                port,
                ws_user,
                prev_instances.get(inst_id),
            )
            new_instances[inst_id] = rec
            # Partage aux AUTRES accessors (le propriétaire possède déjà le host).
            for lg in accessors:
                if lg == login or inst_id not in per_user_instances[lg]:
                    continue
                email = emails.get(lg)
                if not email:
                    # Sans email → non partageable (login Termix = email, spec 18 T5).
                    _log.warning("bastion_share_no_email", login=lg, ws_id=ws_id)
                    continue
                uid = await tx.find_user_id(email)  # compte du user (fusionné après link)
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
            # LIER le compte OIDC de chaque accessor à son compte interne (email)
            # plutôt que partager : `link-oidc-to-password` fusionne l'OIDC dans le
            # compte local → le login OIDC utilise LE compte interne (propriétaire des
            # hosts) → un seul compte, plus de partage. Best-effort ; idempotent (une
            # fois lié, plus de compte OIDC séparé → find renvoie None au prochain tour).
            for lg in accessors:
                if inst_id not in per_user_instances[lg]:
                    continue
                email = emails.get(lg)
                if not email:
                    continue
                oidc_uid = await tx.find_user_id(email, oidc=True)
                if oidc_uid is None:
                    continue
                try:
                    await tx.link_oidc_to_password(oidc_uid, email)
                    _log.info(
                        "termix_oidc_linked",
                        login=lg,
                        email=email,
                        oidc_uid=oidc_uid,
                        instance=inst.get("name"),
                    )
                except Exception as exc:
                    _log.warning("termix_oidc_link_failed", login=lg, email=email, error=str(exc))

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
        # Ne provisionner QUE les workspaces démarrés : le `ssh_port` reste sticky
        # après un stop, mais un workspace arrêté n'a pas de sshd joignable (spec 18
        # T5) — le host est (re)créé au prochain `up`.
        if not status or status.get("status") != "running":
            continue
        owner = status.get("login") or login
        try:
            res = await provision_workspace(str(owner), ws_id)
            if res.get("pending"):
                warnings.append(f"{ws_id} : partage en attente {res['pending']}")
        except Exception as exc:  # best-effort : n'annule pas l'association
            _log.warning("provision_user_access_failed", login=login, ws_id=ws_id, error=str(exc))
            warnings.append(f"{ws_id} : {exc}")
    return warnings


async def deprovision_user_from_instance(conn: Any, login: str, instance_id: str) -> list[str]:
    """Dé-association user↔instance (spec 18 T5) : sur l'instance retirée, supprime
    les hosts que l'user possède (+ leur état) puis **supprime son compte Termix**
    (il ne peut plus s'y connecter). Best-effort → liste d'avertissements."""
    if not enabled():
        return []
    inst = await ti.get(conn, instance_id)
    if inst is None:
        return []
    warnings: list[str] = []
    apikey = await _apikey(inst["apikey_secret"], conn)
    email = (await owner_identity_subject(login)).get("email")
    # Purge de l'état : entrées de cette instance pour les workspaces de l'user.
    for h in await list_ssh_hosts_db(conn):
        if h.get("login") != login:
            continue
        state = await _load_state(h["ws_id"])
        if not state:
            continue
        instances = dict(state.get("instances", {}))
        if instances.pop(instance_id, None) is not None:
            await _save_state(h["ws_id"], {**state, "instances": instances})

    async with TermixClient(inst["url"], apikey) as tx:
        uid = await tx.find_user_id(email) if email else None  # compte du user
        # Supprimer TOUS les hosts de l'user EN TANT QUE lui (liste owner-scoped) :
        # nettoie doublons/orphelins ET débloque la suppression du compte (Termix
        # refuse un delete-user en 500 tant que le compte possède des hosts ; l'admin
        # ne peut pas supprimer les hosts d'un autre user → clé éphémère de l'user).
        if uid is not None:
            key_id, token = await tx.create_apikey_for_user(
                uid, f"portal-deprovision-{login}", _apikey_expiry()
            )
            if token:
                try:
                    async with TermixClient(inst["url"], token) as otx:
                        for host_id in await otx.list_host_ids() or []:
                            try:
                                await otx.delete_host(host_id)
                            except Exception as exc:
                                warnings.append(f"host {host_id} : {exc}")
                        # Puis les credentials (sinon delete-user → 500 FK NOT NULL).
                        for cred_id in await otx.list_credential_ids():
                            try:
                                await otx.delete_credential(cred_id)
                            except Exception as exc:
                                warnings.append(f"credential {cred_id} : {exc}")
                finally:
                    if key_id:
                        try:
                            await tx.delete_apikey(key_id)
                        except Exception:
                            _log.warning("termix_apikey_cleanup_failed", key_id=key_id)
            # Purge des apikeys RÉSIDUELLES de l'user (portal-provision-* accumulées) :
            # elles bloquent delete-user (FK NOT NULL sur apikey.userId).
            try:
                n = await tx.delete_user_apikeys(uid, email)
                if n:
                    _log.info("termix_user_apikeys_purged", login=login, count=n)
            except Exception as exc:
                warnings.append(f"purge apikeys {email} : {exc}")
        # Puis supprimer le compte — best-effort. L'endpoint EXIGE `username` (email).
        #
        # ⚠️ BUG TERMIX UPSTREAM (à réactiver quand corrigé) : la suppression d'un
        # compte échoue en 500 `SQLITE_CONSTRAINT_NOTNULL: audit_logs.user_id` — leur
        # `deleteUserAndRelatedData` met `audit_logs.user_id` à NULL alors que la
        # colonne est NOT NULL. Reproductible AUSSI dans l'IHM Termix (pas notre code).
        # Même famille que Termix-SSH/Support#322 (« Unable to delete user », fermé,
        # variante FOREIGN KEY). En attendant le fix Termix, ce delete échoue → on
        # garde le code (best-effort) : les ACCÈS sont déjà retirés ci-dessus
        # (hosts/credentials/apikeys), seule la coquille du compte subsiste.
        if email and uid is not None:
            try:
                await tx.delete_user(username=email)
                _log.info(
                    "termix_user_deleted", login=login, email=email, instance=inst.get("name")
                )
            except Exception as exc:
                _log.warning("termix_user_delete_failed", login=login, email=email, error=str(exc))
                warnings.append(f"suppression compte Termix {email} : {exc}")
    return warnings


async def deprovision_workspace(
    login: str, ws_id: str, *, purge_state: bool = True
) -> dict[str, Any]:
    """Retire host + credential Termix sur toutes les instances. 404 tolérés.

    `purge_state=True` (delete du workspace) : supprime aussi le secret d'état
    (clé SSH comprise) — nettoyage complet. `purge_state=False` (stop) : conserve
    la **clé SSH** (elle reste bakée dans l'`authorized_keys` du conteneur ; la
    régénérer casserait le SSH au restart) et vide juste `instances` → un restart
    recrée proprement les hosts.
    """
    _require_enabled()
    state = await _load_state(ws_id)
    if state is None:
        return {"ws_id": ws_id, "termix_deleted": False, "instances": []}
    instances: dict[str, Any] = dict(state.get("instances", {}))
    # Union état + instances actuellement résolues pour le propriétaire : un stop
    # précédent qui a échoué à supprimer (clé admin sur host user-owned) a pu vider
    # l'état tout en laissant des hosts → on balaie aussi les instances courantes.
    inst_ids = set(instances)
    async with _get_engine().connect() as conn:
        owner_email = (await owner_identity_subject(login)).get("email")
        with contextlib.suppress(Exception):
            inst_ids |= {i["id"] for i in await uti.resolve_instances_for_user(conn, login)}
    deleted: list[str] = []
    for inst_id in inst_ids:
        async with _get_engine().connect() as conn:
            inst = await ti.get(conn, inst_id)
            if inst is None:
                continue
            apikey = await _apikey(inst["apikey_secret"], conn)
        async with TermixClient(inst["url"], apikey) as tx:
            # Suppression par NOM et EN TANT QUE le propriétaire (les hosts lui
            # appartiennent : l'apikey admin ne les voit pas). Nettoie les doublons.
            n = await _delete_ws_hosts_as_owner(tx, inst, ws_id, owner_email)
            _log.info("bastion_hosts_removed", ws_id=ws_id, instance=inst.get("name"), count=n)
        deleted.append(inst_id)
    if purge_state:
        async with _get_engine().begin() as conn:
            await sysec.delete_system_secret(_slug(ws_id), conn)
    else:
        # Conserve la clé SSH, vide les hosts (recréés au prochain up).
        await _save_state(ws_id, {"login": login, "key": state.get("key"), "instances": {}})
    _log.info("bastion_deprovisioned", ws_id=ws_id, instances=deleted, purge_state=purge_state)
    return {"ws_id": ws_id, "termix_deleted": True, "instances": deleted}
