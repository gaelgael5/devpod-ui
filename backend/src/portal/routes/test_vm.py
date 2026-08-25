"""Création d'une VM de test attachée à un workspace (lot C+D).

L'utilisateur ne fournit que l'hyperviseur et le vmid ; tous les autres args sont
figés par le paramétrage admin (`test_host_params` du type). Le host créé est marqué
`usage=tests` et associé au workspace.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth.rbac import UserInfo, require_user
from ..compose import service as csvc
from ..compose.db import (
    delete_deployments_for_node,
    get_deployment_by_name_node,
    get_template,
)
from ..config.models import (
    _PROXMOX_NAME_RE,
    GlobalConfig,
    HostConfig,
    Hypervisor,
    MachineProfile,
)
from ..config.store import load_global, load_user
from ..db.engine import _get_engine, get_conn
from ..db.global_config import save_global_db, set_cached_global
from ..db.machine_profiles import get_profile
from ..db.mcp_audit import record as _audit_record
from ..db.recipes import load_recipes_as_dict
from ..db.test_hosts import (
    assign_test_host,
    count_owned_test_hosts,
    delete_test_host_link,
    get_test_host_message_id,
    is_owned_test_host,
    list_shared_targets,
    list_test_host_links,
    list_test_hosts_detailed,
    list_test_hosts_with_share,
    next_test_alias,
    remove_test_host,
    set_test_host_message_id,
    upsert_test_host_link,
)
from ..devpod.host_exec import run_host_command
from ..devpod.ssh_exec import run_ssh_capture
from ..devpod.test_host_share import ShareError, add_share, node_for_host, remove_share
from ..devpod.test_vm import (
    build_test_host_views,
    build_test_vm_args,
    host_cert_ready,
    map_result_to_host,
    parse_last_json,
    replace_host_ip,
    substitute_param_vars,
)
from ..devpod.vm_init import (
    CONTAINER_KEYGEN_CMD,
    build_container_ssh_config_cmd,
    build_container_ssh_config_remove_cmd,
    build_portal_key_inject_script,
    build_vm_root_inject_script,
    generate_ed25519_keypair,
    generate_root_password,
)
from ..events.bus import emit_event
from ..messages.renderer import build_host_context
from ..messages.service import delete_message as msg_delete
from ..messages.service import render_and_create
from ..net import build_resolve_fqdn, resolve_ipv4
from ..profiles.provisioning import apply_profile_recipes, deploy_profile_services
from ..routes.host_recipes import _read_install_script as _read_recipe_script
from ..secrets.system import (
    delete_system_secret,
    reveal_system_secret,
    store_system_cert,
    store_system_secret,
)
from ..settings import get_settings
from ..vault.pin import (
    PinLockedError,
    PinNotSetupError,
    PinWrongError,
    VaultDisabledError,
    unlock_pin,
)
from .proxmox import (
    _fetch_spec,
    _run_destroy_script,
    _ssh_opts,
    _ssh_stream,
    _substitute,
    find_identifier_arg,
    missing_placeholders,
    resolve_node_script,
    spec_arg_defaults,
)
from .vault import _sid

_log = structlog.get_logger(__name__)
router = APIRouter(tags=["test-vm"])

_VMID_RE = re.compile(r"^[0-9]{1,9}$")
_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
# Utilisateur SSH POSIX ; hôte = IPv4 ou nom DNS. Strict pour éviter toute
# injection dans `<user>@<host>` (utilisé en commande ssh côté portail/container).
_SSH_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_SSH_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,253}[A-Za-z0-9])?$")
_PIN_RE = re.compile(r"^\d{6}$")
_AUDIT_ROOT_PW_REVEAL = "me.test_host.root_password.reveal"


def _usable_type_names(cfg: GlobalConfig) -> set[str]:
    """Types d'hyperviseur prêts pour les VM de test : add_script + paramétrage."""
    return {t.name for t in cfg.hypervisor_types if t.add_script and t.test_host_params}


@router.get("/test-hypervisors")
async def list_test_hypervisors(
    user: UserInfo = Depends(require_user),
) -> list[dict[str, str]]:
    """Hyperviseurs utilisables pour créer une VM de test."""
    cfg = load_global()
    usable = _usable_type_names(cfg)
    labels = {t.name: (t.label or t.name) for t in cfg.hypervisor_types}
    return [
        {"name": n.name, "type": n.hypervisor_type, "label": labels[n.hypervisor_type]}
        for n in cfg.hypervisors
        if n.hypervisor_type in usable
    ]


@router.get("/test-hypervisors/{name}/script")
async def get_test_hypervisor_script(
    name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, object]:
    """Spec du node résolue (pour proposer les valeurs du vmid)."""
    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == name), None)
    if node is None or node.hypervisor_type not in _usable_type_names(cfg):
        raise HTTPException(status_code=404, detail=f"Test hypervisor {name!r} not available")
    return await resolve_node_script(node, cfg)


async def _init_vm_ssh(
    login: str, ws: str, host: HostConfig, node: Hypervisor, alias: str
) -> AsyncIterator[bytes]:
    """Lot E : injecte la pubkey du container et un mot de passe root dans la VM."""
    if host.type != "ssh" or not host.address:
        yield b"\n==> Init SSH ignoree (host sans adresse SSH)\n"
        return
    yield b"\n==> Initialisation SSH (cle du container + acces root)...\n"
    _rc, out, _err = await run_ssh_capture(login, f"{login}-{ws}", CONTAINER_KEYGEN_CMD)
    pubkey = next((ln.strip() for ln in out.splitlines() if ln.startswith("ssh-")), "")
    if not pubkey:
        yield b"==> ERREUR : cle publique du container introuvable\n"
        return

    password = generate_root_password()
    inject = build_vm_root_inject_script(pubkey, password, host.address)
    ssh_cmd = ["ssh", *_ssh_opts(node), f"{node.ssh_user}@{node.address}", "bash -s"]
    proc = await asyncio.create_subprocess_exec(
        *ssh_cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, serr = await asyncio.wait_for(proc.communicate(input=inject.encode()), timeout=60.0)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        yield b"==> ERREUR : injection SSH VM (timeout)\n"
        return
    if proc.returncode != 0:
        detail = serr.decode("utf-8", errors="replace").strip()[:300]
        yield f"==> ERREUR injection VM : {detail}\n".encode()
        return

    async with _get_engine().begin() as conn:
        await store_system_secret(
            slug=f"host.{host.name}.root-password",
            label=f"Root password — {host.name}",
            value=password,
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )
    ip = host.address.split("@", 1)[-1]
    yield (
        f"\n==> Accès SSH prêt — login: root  ip: {ip}\n"
        f"==> Mot de passe root : {password}\n"
        "==> (clé du container injectée ; mot de passe stocké côté portail)\n"
    ).encode()

    # Alias SSH persistant dans le container : `ssh testN` joint la VM (root + clé).
    cfg_rc, _cfg_out, cfg_err = await run_ssh_capture(
        login, f"{login}-{ws}", build_container_ssh_config_cmd(alias, ip)
    )
    if cfg_rc == 0:
        yield (
            f"==> Alias SSH '{alias}' ajouté au ~/.ssh/config du container (ssh {alias})\n"
        ).encode()
    else:
        detail = cfg_err.strip()[:200]
        yield f"==> AVERTISSEMENT : alias SSH non écrit ({detail})\n".encode()

    # Activation SSH portail : génère une clé ED25519 dédiée, l'injecte dans la VM
    # et met à jour host_cert_slug — permet d'utiliser cette machine pour les services compose.
    yield b"\n==> Activation SSH portail (services compose)...\n"
    try:
        portal_priv, portal_pub = await generate_ed25519_keypair()
    except Exception as exc:
        yield f"==> AVERTISSEMENT : génération clé SSH portail échouée ({exc})\n".encode()
        return

    portal_inject = build_portal_key_inject_script(portal_pub, host.address)
    ssh_cmd2 = ["ssh", *_ssh_opts(node), f"{node.ssh_user}@{node.address}", "bash -s"]
    proc2 = await asyncio.create_subprocess_exec(
        *ssh_cmd2,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, serr2 = await asyncio.wait_for(
            proc2.communicate(input=portal_inject.encode()), timeout=30.0
        )
    except TimeoutError:
        proc2.kill()
        await proc2.wait()
        yield "==> AVERTISSEMENT : injection clé SSH portail (timeout)\n".encode()
        return
    if proc2.returncode != 0:
        detail2 = serr2.decode("utf-8", errors="replace").strip()[:300]
        yield f"==> AVERTISSEMENT : injection clé SSH portail : {detail2}\n".encode()
        return

    slug = f"compose.{host.name}"
    async with _get_engine().begin() as conn:
        await store_system_cert(
            slug=slug,
            label=f"Clé SSH portail — {host.name}",
            private_pem=portal_priv,
            public_key=portal_pub,
            cert_type="ssh",
            storage_type="local",
            vault_identifier="",
            conn=conn,
        )
        new_cfg = load_global()
        for h in new_cfg.hosts:
            if h.name == host.name:
                h.host_cert_slug = slug
                break
        await save_global_db(new_cfg, conn)
    set_cached_global(new_cfg)  # après commit réussi seulement (bug 034)

    yield "==> SSH portail actif — services compose disponibles sur cette machine\n".encode()


@router.get("/workspaces/{ws}/test-hosts")
async def list_workspace_test_hosts(
    ws: str,
    user: UserInfo = Depends(require_user),
) -> list[dict[str, str]]:
    """Machines de test attachées à un workspace de l'utilisateur (alias, name, ip, vmid)."""
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    user_cfg = await load_user(user.login)
    if not any(w.name == ws for w in user_cfg.workspaces):
        raise HTTPException(status_code=404, detail=f"Workspace {ws!r} not found")
    async with _get_engine().connect() as conn:
        triples = await list_test_hosts_with_share(user.login, ws, conn)
    cfg = load_global()
    shared_map = {name: (sf or "") for name, _alias, sf in triples}
    views = build_test_host_views([(n, a) for n, a, _ in triples], cfg.hosts)
    for v in views:
        # `sharedFrom` non vide = VM partagée-vers ce workspace (bloc en lecture
        # seule côté carte : pas de suppression/recréation).
        v["sharedFrom"] = shared_map.get(v["name"], "")
    return views


class CreateTestVmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypervisor: str
    vmid: str
    # Profil de machine : ses parametres remplacent ceux du type, et ses
    # recettes sont posees apres la creation. Vide = comportement historique
    # (parametres figes du type), le temps que les profils soient saisis.
    profile_slug: str = ""


@dataclass
class _CreateJob:
    """Job de provisioning d'une VM de test, DÉCOUPLÉ de la requête HTTP.

    Le provisioning tourne en tâche de fond et écrit ici sa progression + son
    statut. Perdre la connexion cliente n'interrompt PAS le job : la machine est
    enregistrée quoi qu'il arrive ; l'IHM se contente de poller cet état.
    """

    login: str
    chunks: list[bytes] = field(default_factory=list)
    status: str = "running"  # running | ok | failed
    finished_at: datetime | None = None

    def write(self, data: bytes) -> None:
        self.chunks.append(data)

    def finish(self, status: str) -> None:
        self.status = status
        self.finished_at = datetime.now(UTC)

    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8", errors="replace")


# Registre des jobs de création en cours/récents (clé = job_id). Les tâches sont
# référencées fortement (une tâche asyncio non référencée peut être GC avant la fin).
_create_jobs: dict[str, _CreateJob] = {}
_create_tasks: set[asyncio.Task[None]] = set()
_JOB_RETENTION_S = 900.0


def _purge_finished_jobs() -> None:
    """Retire les jobs terminés depuis plus de _JOB_RETENTION_S (anti-fuite mémoire)."""
    now = datetime.now(UTC)
    stale = [
        jid
        for jid, j in _create_jobs.items()
        if j.finished_at is not None and (now - j.finished_at).total_seconds() > _JOB_RETENTION_S
    ]
    for jid in stale:
        _create_jobs.pop(jid, None)


async def _provision_test_vm(
    job: _CreateJob,
    *,
    login: str,
    ws: str,
    node: Hypervisor,
    commands: list[str],
    display: list[str],
    alias: str,
    profile: MachineProfile | None = None,
    vmid: str,
) -> None:
    """Provisionne la VM et ENREGISTRE la machine. Tâche de fond indépendante de la
    requête : une déconnexion cliente ne l'interrompt pas (la machine est ajoutée)."""
    try:
        header = "==> Création VM de test\n" + "\n".join(f"    {c}" for c in display) + "\n\n"
        job.write(header.encode("utf-8"))
        _log.info("test_vm_provision_start", login=login, ws=ws, node=node.name, vmid=vmid)
        buf = bytearray()
        # Miroir vers Loki, ligne par ligne : la progression du provisioning (script de
        # clone) devient observable en centralisé (Grafana/Loki), sans dépendre du flux
        # navigateur. Seule la phase CLONE est journalisée — la sortie de _init_vm_ssh
        # (plus bas) contient le mot de passe root et ne doit JAMAIS partir dans Loki.
        line_buf = ""
        async for chunk in _ssh_stream(node, commands):
            buf.extend(chunk)
            job.write(chunk)
            line_buf += chunk.decode("utf-8", errors="replace")
            while "\n" in line_buf:
                line, line_buf = line_buf.split("\n", 1)
                line = line.rstrip("\r")
                if line.strip():
                    _log.info("test_vm_provision_out", vmid=vmid, ws=ws, line=line)
        if line_buf.strip():
            _log.info("test_vm_provision_out", vmid=vmid, ws=ws, line=line_buf.rstrip("\r"))

        # Extrait borné de la sortie pour tracer côté serveur la cause d'un échec.
        output = buf.decode("utf-8", errors="replace")
        tail = output[-2000:]
        result: dict[str, Any] | None = parse_last_json(output)
        if result is None:
            _log.warning(
                "test_vm_create_failed",
                login=login,
                ws=ws,
                node=node.name,
                vmid=vmid,
                reason="no_json_result",
                output_tail=tail,
            )
            job.write(b"\n==> ERREUR : pas de resultat JSON du script de creation\n")
            job.finish("failed")
            return
        host = map_result_to_host(result, vmid, node.name)
        if not host.name:
            _log.warning(
                "test_vm_create_failed",
                login=login,
                ws=ws,
                node=node.name,
                vmid=vmid,
                reason="no_hostname",
                output_tail=tail,
            )
            job.write(b"\n==> ERREUR : le script n'a pas retourne de nom d'hote\n")
            job.finish("failed")
            return

        new_cfg = load_global()
        if any(h.name == host.name for h in new_cfg.hosts):
            _log.warning(
                "test_vm_create_failed",
                login=login,
                ws=ws,
                node=node.name,
                vmid=vmid,
                reason="host_name_conflict",
                host=host.name,
            )
            job.write(f"\n==> ERREUR : un host nomme {host.name!r} existe deja\n".encode())
            job.finish("failed")
            return
        if profile is not None:
            # Sans cette reference, on ne sait pas six mois plus tard avec quel
            # profil la machine a ete montee ni ce qui devait y etre pose.
            host.profile_slug = profile.slug
        new_cfg.hosts.append(host)
        async with _get_engine().begin() as conn:
            await save_global_db(new_cfg, conn)
            await assign_test_host(login, ws, host.name, alias, conn)
        set_cached_global(new_cfg)  # après commit réussi seulement (bug 034)

        await emit_event(
            "test_server.created",
            actor=login,
            workspace=ws,
            subject={
                "host_name": host.name,
                "alias": alias,
                "address": host.address,
                "hypervisor": node.name,
            },
        )
        _log.info("test_vm_create_done", login=login, ws=ws, host=host.name, alias=alias, vmid=vmid)

        # Message contextuel pour les agents (non-bloquant).
        try:
            user_cfg = await load_user(login)
            ctx = build_host_context(
                owner_login=login,
                workspace_name=ws,
                host_name=host.name,
                alias=alias,
                address=host.address,
                culture=user_cfg.culture,
            )
            async with _get_engine().begin() as conn:
                msg_id = await render_and_create(
                    conn,
                    key="test_host_available",
                    culture=user_cfg.culture,
                    owner_login=login,
                    workspace_name=ws,
                    msg_type="test_host",
                    ctx=ctx,
                )
                if msg_id is not None:
                    await set_test_host_message_id(host.name, msg_id, conn)
        except Exception:
            _log.warning("test_host_message_create_failed", host=host.name, exc_info=True)

        job.write(
            f"\n==> VM de test '{host.name}' creee et attachee au workspace '{ws}'\n".encode()
        )
        async for msg in _init_vm_ssh(login, ws, host, node, alias):
            job.write(msg)

        # Recettes du profil, APRES l'init SSH : elles s'appliquent par SSH.
        # Un echec est signale sans detruire la machine — elle est creee, et la
        # recette se re-applique depuis sa fiche une fois la cause levee.
        if profile is not None and profile.recipes:
            async with _get_engine().connect() as conn:
                catalogue = await load_recipes_as_dict(login, conn)
            live = load_global()
            host_live = next((h for h in live.hosts if h.name == host.name), host)

            async def _run(command: str, *, timeout: float) -> tuple[int, str, str]:
                return await run_host_command(host_live, command, timeout=timeout)

            async for ligne in apply_profile_recipes(
                profile,
                host=host_live,
                catalogue=catalogue,
                run=_run,
                read_script=lambda rid: _read_recipe_script(rid, login),
            ):
                job.write(ligne.encode())

        # Services du profil, avant l'auto-start : le profil est un choix
        # explicite pour CETTE machine, l'auto-start une preference globale.
        if profile is not None and profile.services:
            live_services = load_global()
            host_srv = next((h for h in live_services.hosts if h.name == host.name), host)
            srv_user_cfg = await load_user(login)
            async with _get_engine().begin() as conn:
                modeles: dict[str, object] = {}
                for service in profile.services:
                    tpl = await get_template(conn, service.template_id)
                    if tpl is not None:
                        modeles[service.template_id] = tpl

                async def _deja(nom: str, _conn: AsyncConnection = conn) -> bool:
                    return await get_deployment_by_name_node(_conn, nom, host.name) is not None

                async def _deploy(
                    *,
                    name: str,
                    template: Any,
                    node_id: str,
                    env_values: dict[str, str],
                    _conn: AsyncConnection = conn,
                ) -> object:
                    return await csvc.deploy(
                        _conn,
                        name=name,
                        template=template,
                        node_id=node_id,
                        owner_login=login,
                        secret_ns=srv_user_cfg.secret_ns,
                        env_values=env_values,
                    )

                async for ligne in deploy_profile_services(
                    profile,
                    host=host_srv,
                    templates=modeles,
                    deploy=_deploy,
                    already_deployed=_deja,
                ):
                    job.write(ligne.encode())

        # Auto-start : uniquement si le SSH portail a été activé (host_cert_slug posé).
        if host_cert_ready(load_global().hosts, host.name):
            auto_user_cfg = await load_user(login)
            async with _get_engine().begin() as conn:
                async for line in csvc.deploy_auto_start_templates(
                    conn,
                    owner_login=login,
                    secret_ns=auto_user_cfg.secret_ns,
                    node_id=host.name,
                ):
                    job.write(line.encode())
        job.finish("ok")
    except Exception:
        _log.error("test_vm_provision_crashed", login=login, ws=ws, vmid=vmid, exc_info=True)
        job.write(b"\n==> ERREUR interne du provisioning (voir logs serveur)\n")
        job.finish("failed")


@router.post("/workspaces/{ws}/test-vm")
async def create_test_vm(
    ws: str,
    body: CreateTestVmRequest,
    user: UserInfo = Depends(require_user),
) -> JSONResponse:
    """Lance la création d'une VM de test EN TÂCHE DE FOND et retourne un job_id (202).

    Le provisioning (clone + enregistrement de la machine + init SSH) est découplé de
    cette requête : perdre la connexion n'interrompt PAS la création — la machine est
    enregistrée quoi qu'il arrive. L'IHM poll la progression via GET .../test-vm/create/{job_id}.
    """
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    if not _VMID_RE.fullmatch(body.vmid):
        raise HTTPException(status_code=422, detail="vmid must be numeric")

    user_cfg = await load_user(user.login)
    if not any(w.name == ws for w in user_cfg.workspaces):
        raise HTTPException(status_code=404, detail=f"Workspace {ws!r} not found")

    cfg = load_global()
    node = next((n for n in cfg.hypervisors if n.name == body.hypervisor), None)
    if node is None or node.hypervisor_type not in _usable_type_names(cfg):
        raise HTTPException(
            status_code=404, detail=f"Test hypervisor {body.hypervisor!r} not available"
        )
    hyp_type = next(t for t in cfg.hypervisor_types if t.name == node.hypervisor_type)

    spec = await _fetch_spec(node, cfg)
    identifier_arg = find_identifier_arg(spec)
    if identifier_arg is None:
        raise HTTPException(status_code=422, detail="Hypervisor spec has no identifier arg")

    commands_raw: list[str] = spec.get("commands", [])  # type: ignore[assignment]
    settings = get_settings()
    login = user.login
    # Défauts déclarés par la spec EN BASE, surchargés par les params stockés du type :
    # un arg ajouté à la spec après coup (ex. SWAP_PERCENT=25) s'applique même si les
    # params n'ont pas été re-saisis (sinon placeholder littéral → script en échec).
    # Un profil prime sur les parametres figes du type : c'est lui que
    # l'utilisateur a choisi. Les defauts declares par la spec restent la base,
    # pour qu'un arg ajoute apres coup s'applique quand meme.
    profile: MachineProfile | None = None
    if body.profile_slug:
        async with _get_engine().connect() as conn:
            profile = await get_profile(body.profile_slug, conn)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Profil {body.profile_slug!r} introuvable")
        if profile.hypervisor_type != node.hypervisor_type:
            # Les parametres d'un profil sont types par la spec d'un type donne.
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Profil {profile.slug!r} prevu pour {profile.hypervisor_type!r}, "
                    f"machine sur {node.hypervisor_type!r}"
                ),
            )
        figes = dict(profile.params)
    else:
        figes = dict(hyp_type.test_host_params)
    merged_params = {**spec_arg_defaults(spec), **figes}
    args = build_test_vm_args(merged_params, identifier_arg, body.vmid)
    args["PORTAL_URL"] = cfg.server.external_url
    args["PORTAL_TOKEN"] = settings.portal_api_key
    args["PORTAL_PVE_NODE"] = node.name

    # Substitution des variables <NOM> dans les valeurs paramétrées (ex. NODE_NAME) :
    # args (dont <NEW_VMID>) + <N>/<N+1> = nb de VM de test du workspace.
    # alias = plus petit `testN` libre (réutilise les numéros des machines supprimées).
    async with _get_engine().connect() as conn:
        detailed = await list_test_hosts_detailed(login, ws, conn)
        # `<N>` = nombre de VM POSSÉDÉES (une VM partagée-vers ce workspace ne
        # décale pas la numérotation) ; l'alias évite toutes les collisions ssh.
        n = await count_owned_test_hosts(login, ws, conn)
    alias = next_test_alias([a for _, a in detailed])
    args = substitute_param_vars(args, {"N": str(n), "N+1": str(n + 1)})

    # Fail-fast : un placeholder {KEY} du script sans valeur dans les paramètres du
    # type d'hyperviseur partirait littéral au script (échec cryptique). On le
    # détecte ici avec un message actionnable (ex. SWAP_PERCENT manquant).
    missing = missing_placeholders(commands_raw, args)
    if missing:
        _log.warning(
            "test_vm_create_missing_params",
            login=login,
            ws=ws,
            node=node.name,
            hypervisor_type=node.hypervisor_type,
            missing=sorted(missing),
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"Paramètres manquants pour le type d'hyperviseur "
                f"{node.hypervisor_type!r} : {', '.join(sorted(missing))}. "
                "Renseignez-les dans les paramètres du type (/admin/hypervisor-types)."
            ),
        )

    commands = [_substitute(c, args) for c in commands_raw]
    display = [_substitute(c, {**args, "PORTAL_TOKEN": "***"}) for c in commands_raw]

    _log.info("test_vm_create", login=login, ws=ws, node=node.name, vmid=body.vmid)

    _purge_finished_jobs()
    job = _CreateJob(login=login)
    job_id = uuid.uuid4().hex
    _create_jobs[job_id] = job
    task = asyncio.create_task(
        _provision_test_vm(
            job,
            login=login,
            ws=ws,
            node=node,
            commands=commands,
            display=display,
            alias=alias,
            vmid=body.vmid,
            profile=profile,
        )
    )
    _create_tasks.add(task)
    task.add_done_callback(_create_tasks.discard)
    return JSONResponse({"job_id": job_id}, status_code=202)


@router.get("/workspaces/{ws}/test-vm/create/{job_id}")
async def get_test_vm_create_progress(
    ws: str,
    job_id: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, Any]:
    """Progression d'un job de création : log accumulé + statut (running|ok|failed).

    L'IHM poll cet endpoint. Le job survit à la déconnexion cliente ; il est conservé
    ~15 min après la fin pour la reconnexion, puis purgé.
    """
    job = _create_jobs.get(job_id)
    if job is None or job.login != user.login:
        raise HTTPException(status_code=404, detail="job de création introuvable")
    return {"status": job.status, "log": job.text()}


@router.delete("/workspaces/{ws}/test-vm/{host_name}", status_code=204)
async def delete_test_vm(
    ws: str,
    host_name: str,
    user: UserInfo = Depends(require_user),
) -> None:
    """Supprime une machine de test : détruit la VM puis nettoie côté portail.

    Séquence résiliente : la destruction de la VM et le nettoyage du container sont
    best-effort (loggés sur échec) ; l'état portail est toujours nettoyé.
    """
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    if not _PROXMOX_NAME_RE.fullmatch(host_name):
        raise HTTPException(status_code=422, detail="Invalid host name")

    login = user.login
    async with _get_engine().connect() as conn:
        detailed = await list_test_hosts_detailed(login, ws, conn)
        owned = await is_owned_test_host(login, ws, host_name, conn)
        shared_targets = await list_shared_targets(login, host_name, conn)
    alias = next((a for n, a in detailed if n == host_name), None)
    if alias is None:
        raise HTTPException(
            status_code=404, detail=f"Test host {host_name!r} not found for workspace {ws!r}"
        )
    if not owned:
        # Garde de cycle de vie : une VM seulement PARTAGÉE-vers ce workspace ne
        # peut pas être détruite depuis lui (seul le propriétaire le peut).
        raise HTTPException(
            status_code=403,
            detail="Cette VM vous est partagée : seul son propriétaire peut la supprimer.",
        )

    cfg = load_global()
    host_cfg = next((h for h in cfg.hosts if h.name == host_name), None)

    # 0. Nettoyer les partages (bloc ssh config des cibles + message). La VM va être
    #    détruite → pas de retrait de clé sur la VM (node=None), best-effort.
    if host_cfg is not None:
        for target_ws, _alias, _msg in shared_targets:
            try:
                await remove_share(login, host_cfg, None, target_ws)
            except Exception:
                _log.warning("test_vm_share_cleanup_failed", host=host_name, target=target_ws)

    # 1. Détruire la VM sur l'hyperviseur (best-effort, ne lève pas).
    if host_cfg is not None:
        await _run_destroy_script(cfg, host_cfg)

    # 2. Retirer l'alias du ~/.ssh/config du container (best-effort).
    try:
        await run_ssh_capture(login, f"{login}-{ws}", build_container_ssh_config_remove_cmd(alias))
    except Exception:
        _log.warning("test_vm_ssh_config_cleanup_failed", host=host_name, exc_info=True)

    # 3-6. Nettoyage portail (secret root, association → libère l'alias, host config,
    #      déploiements compose).
    async with _get_engine().begin() as conn:
        message_id = await get_test_host_message_id(host_name, conn)
        await delete_system_secret(f"host.{host_name}.root-password", conn)
        await remove_test_host(host_name, conn)
        # Les conteneurs sont partis avec la VM : sans ca leurs lignes lui
        # survivent et ressortent sur la machine suivante qui porte le meme nom.
        purges = await delete_deployments_for_node(conn, host_name)
        if purges:
            _log.info("test_vm_deployments_purged", host=host_name, count=purges)
        if host_cfg is not None:
            cfg.hosts = [h for h in cfg.hosts if h.name != host_name]
            await save_global_db(cfg, conn)
        await msg_delete(conn, message_id)
    if host_cfg is not None:
        set_cached_global(cfg)  # après commit réussi seulement (bug 034)

    _log.info("test_vm_deleted", login=login, ws=ws, host=host_name, alias=alias)
    await emit_event(
        "test_server.deleted",
        actor=login,
        workspace=ws,
        subject={"host_name": host_name, "alias": alias},
    )


@router.post("/workspaces/{ws}/test-vm/{host_name}/resolve-ip")
async def resolve_test_vm_ip(
    ws: str,
    host_name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, str]:
    """Re-résout l'IP DHCP d'une machine de test via DNS (nom + domaine local).

    Met à jour `host.address` et le bloc `~/.ssh/config` du container.
    """
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    if not _PROXMOX_NAME_RE.fullmatch(host_name):
        raise HTTPException(status_code=422, detail="Invalid host name")

    login = user.login
    async with _get_engine().connect() as conn:
        detailed = await list_test_hosts_detailed(login, ws, conn)
        owned = await is_owned_test_host(login, ws, host_name, conn)
    alias = next((a for n, a in detailed if n == host_name), None)
    if alias is None:
        raise HTTPException(
            status_code=404, detail=f"Test host {host_name!r} not found for workspace {ws!r}"
        )
    if not owned:
        raise HTTPException(
            status_code=403,
            detail="Cette VM vous est partagée : seul son propriétaire peut la re-résoudre.",
        )

    cfg = load_global()
    host_cfg = next((h for h in cfg.hosts if h.name == host_name), None)
    if host_cfg is None:
        raise HTTPException(status_code=404, detail=f"Host {host_name!r} not found")

    fqdn = build_resolve_fqdn(host_name, cfg.server.local_domain)
    try:
        new_ip = await resolve_ipv4(fqdn)
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"Unresolvable: {fqdn} ({exc})") from exc

    new_address = replace_host_ip(host_cfg.address, new_ip)
    cfg.hosts = [
        h.model_copy(update={"address": new_address}) if h.name == host_name else h
        for h in cfg.hosts
    ]
    async with _get_engine().begin() as conn:
        await save_global_db(cfg, conn)
    set_cached_global(cfg)  # après commit réussi seulement (bug 034)

    # Réécrit le bloc ~/.ssh/config du container avec la nouvelle IP (best-effort).
    try:
        await run_ssh_capture(login, f"{login}-{ws}", build_container_ssh_config_cmd(alias, new_ip))
    except Exception:
        _log.warning("test_vm_ssh_config_refresh_failed", host=host_name, exc_info=True)

    _log.info("test_vm_ip_resolved", login=login, ws=ws, host=host_name, fqdn=fqdn, ip=new_ip)
    await emit_event(
        "test_server.updated",
        actor=login,
        workspace=ws,
        subject={
            "host_name": host_name,
            "alias": alias,
            "address": new_address,
            "password_changed": False,
        },
    )
    return {"ip": new_ip, "fqdn": fqdn}


class UpdateConnectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    host: str
    # None = ne pas toucher au mot de passe stocké ; une valeur remplace le secret.
    password: str | None = None


@router.put("/workspaces/{ws}/test-vm/{host_name}/connection")
async def update_test_vm_connection(
    ws: str,
    host_name: str,
    body: UpdateConnectionBody,
    user: UserInfo = Depends(require_user),
) -> dict[str, str]:
    """Édite les paramètres de connexion MÉMORISÉS d'une machine de test.

    Met à jour `host.address = <username>@<host>` (et réécrit le bloc `~/.ssh/config`
    du container) ; si `password` est fourni, remplace le secret root stocké côté
    portail. N'agit PAS sur la VM : c'est le pendant manuel de `resolve-ip` pour
    recoller l'état portail à la réalité (IP DHCP dérivée, identifiants changés).
    Réservé au workspace PROPRIÉTAIRE de la VM.
    """
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    if not _PROXMOX_NAME_RE.fullmatch(host_name):
        raise HTTPException(status_code=422, detail="Invalid host name")

    username = body.username.strip()
    host = body.host.strip()
    if not _SSH_USER_RE.fullmatch(username):
        raise HTTPException(status_code=422, detail="Invalid SSH username")
    if not _SSH_HOST_RE.fullmatch(host):
        raise HTTPException(status_code=422, detail="Invalid host address")

    login = user.login
    async with _get_engine().connect() as conn:
        detailed = await list_test_hosts_detailed(login, ws, conn)
        owned = await is_owned_test_host(login, ws, host_name, conn)
    alias = next((a for n, a in detailed if n == host_name), None)
    if alias is None:
        raise HTTPException(
            status_code=404, detail=f"Test host {host_name!r} not found for workspace {ws!r}"
        )
    if not owned:
        raise HTTPException(
            status_code=403,
            detail="Cette VM vous est partagée : seul son propriétaire peut la modifier.",
        )

    cfg = load_global()
    host_cfg = next((h for h in cfg.hosts if h.name == host_name), None)
    if host_cfg is None:
        raise HTTPException(status_code=404, detail=f"Host {host_name!r} not found")
    if host_cfg.type != "ssh":
        raise HTTPException(
            status_code=409, detail="Seuls les hosts de test SSH ont des paramètres éditables"
        )

    new_address = f"{username}@{host}"
    cfg.hosts = [
        h.model_copy(update={"address": new_address}) if h.name == host_name else h
        for h in cfg.hosts
    ]
    async with _get_engine().begin() as conn:
        await save_global_db(cfg, conn)
        if body.password is not None:
            # Mémorisé en clair côté portail comme à la création (secret système local).
            await store_system_secret(
                slug=f"host.{host_name}.root-password",
                label=f"Root password — {host_name}",
                value=body.password,
                storage_type="local",
                vault_identifier="",
                conn=conn,
            )
    set_cached_global(cfg)  # après commit réussi seulement (bug 034)

    # Réécrit le bloc ~/.ssh/config du container avec la nouvelle adresse (best-effort).
    try:
        await run_ssh_capture(login, f"{login}-{ws}", build_container_ssh_config_cmd(alias, host))
    except Exception:
        _log.warning("test_vm_ssh_config_refresh_failed", host=host_name, exc_info=True)

    _log.info(
        "test_vm_connection_updated",
        login=login,
        ws=ws,
        host=host_name,
        password_changed=body.password is not None,
    )
    await emit_event(
        "test_server.updated",
        actor=login,
        workspace=ws,
        subject={
            "host_name": host_name,
            "alias": alias,
            "address": new_address,
            "password_changed": body.password is not None,
        },
    )
    return {"alias": alias, "name": host_name, "ip": host, "user": username, "vmid": host_cfg.vmid}


class RevealRootPasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: str

    @field_validator("pin")
    @classmethod
    def _validate_pin(cls, v: str) -> str:
        if not _PIN_RE.fullmatch(v):
            raise ValueError("PIN must be exactly 6 digits")
        return v


async def _audit_root_pw(
    conn: AsyncConnection, login: str, host: str, status: str, error: str | None
) -> None:
    await _audit_record(
        conn,
        apikey_id=None,
        owner_login=login,
        namespaced_name=_AUDIT_ROOT_PW_REVEAL,
        backend_id=host,
        backend_key_id=None,
        latency_ms=None,
        status=status,
        error=error,
    )


async def _audit_root_pw_denied(login: str, host: str, error: str) -> None:
    """Trace un refus dans une transaction DÉDIÉE (le 4xx rollback la conn requête)."""
    try:
        async with _get_engine().begin() as conn:
            await _audit_root_pw(conn, login, host, "denied", error)
    except Exception:
        _log.warning("test_vm_root_pw_audit_failed", host=host, exc_info=True)


@router.post("/workspaces/{ws}/test-vm/{host_name}/root-password/reveal")
async def reveal_test_vm_root_password(
    ws: str,
    host_name: str,
    body: RevealRootPasswordBody,
    request: Request,
    user: UserInfo = Depends(require_user),
    conn: AsyncConnection = Depends(get_conn),
) -> dict[str, str]:
    """Renvoie le mot de passe root d'une machine de test après validation du PIN.

    Ownership et existence du host résolus AVANT le PIN : un accès non autorisé ou un
    host inconnu ne consomme pas de tentative (le lockout protège le PIN, pas le
    routage). Chaque tentative — accordée ou refusée — est tracée dans l'audit.
    """
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    if not _PROXMOX_NAME_RE.fullmatch(host_name):
        raise HTTPException(status_code=422, detail="Invalid host name")

    login = user.login
    if not await is_owned_test_host(login, ws, host_name, conn):
        raise HTTPException(
            status_code=404, detail=f"Test host {host_name!r} not found for workspace {ws!r}"
        )

    try:
        await unlock_pin(login, body.pin, _sid(request), conn)
    except VaultDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PinLockedError as exc:
        await _audit_root_pw_denied(login, host_name, "pin_locked")
        raise HTTPException(
            status_code=423,
            detail={
                "message": "PIN temporarily locked",
                "seconds_remaining": exc.seconds_remaining,
            },
        ) from exc
    except PinWrongError as exc:
        await _audit_root_pw_denied(login, host_name, "pin_wrong")
        _log.warning("test_vm_root_password_reveal_denied", host=host_name, by=login)
        raise HTTPException(status_code=403, detail="Incorrect PIN") from exc
    except PinNotSetupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        value = await reveal_system_secret(f"host.{host_name}.root-password", conn)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"Root password of {host_name!r} not stored"
        ) from exc

    await _audit_root_pw(conn, login, host_name, "ok", None)
    _log.info("test_vm_root_password_revealed", host=host_name, by=login)
    return {"value": value}


@router.get("/workspaces/{ws}/test-hosts/{host_name}/stacks")
async def list_test_host_stacks(
    ws: str,
    host_name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, list[dict[str, str]]]:
    """État docker LIVE de la machine : `stacks` (docker compose ls) + `containers`
    hors compose (docker ps). Vue en direct via le docker de l'hôte.

    Accessible à tout workspace auquel la VM est attachée (possédée OU partagée).
    """
    await _require_ws_and_host(ws, host_name, user.login)
    async with _get_engine().connect() as conn:
        detailed = await list_test_hosts_detailed(user.login, ws, conn)
    if not any(n == host_name for n, _ in detailed):
        raise HTTPException(
            status_code=404, detail=f"Test host {host_name!r} not attached to {ws!r}"
        )
    try:
        # Cache TTL court côté service (be1112a5) : le polling du front ne
        # déclenche plus deux SSH par requête.
        return await csvc.get_host_state(host_name)
    except csvc.ComposeServiceError:
        return {"stacks": [], "containers": []}


# ─── Partage d'une VM de test vers d'autres workspaces (menu ⋮ « Partager ») ──


@router.get("/workspaces/{ws}/test-hosts/{host_name}/shares")
async def get_test_host_shares(
    ws: str,
    host_name: str,
    user: UserInfo = Depends(require_user),
) -> dict[str, list[str]]:
    """Workspaces à qui cette VM (possédée par `ws`) est actuellement partagée."""
    await _require_ws_and_host(ws, host_name, user.login)
    async with _get_engine().connect() as conn:
        if not await is_owned_test_host(user.login, ws, host_name, conn):
            raise HTTPException(
                status_code=404, detail=f"Test host {host_name!r} not owned by {ws!r}"
            )
        targets = await list_shared_targets(user.login, host_name, conn)
    return {"shared": sorted(t[0] for t in targets)}


class ShareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspaces: list[str]


@router.put("/workspaces/{ws}/test-hosts/{host_name}/shares")
async def set_test_host_shares(
    ws: str,
    host_name: str,
    body: ShareBody,
    user: UserInfo = Depends(require_user),
) -> dict[str, list[str]]:
    """Réconcilie l'ensemble des workspaces partagés (cases cochées de la fenêtre).

    Diff vs état courant : les ajouts injectent la clé du container cible sur la
    VM + écrivent son ssh config + créent un message ; les retraits nettoient tout.
    Réservé au workspace PROPRIÉTAIRE de la VM.
    """
    await _require_ws_and_host(ws, host_name, user.login)
    login = user.login

    user_cfg = await load_user(login)
    ws_names = {w.name for w in user_cfg.workspaces}
    desired: set[str] = set()
    for target in body.workspaces:
        if not _WS_NAME_RE.fullmatch(target):
            raise HTTPException(status_code=422, detail=f"Invalid workspace name: {target!r}")
        if target == ws:
            raise HTTPException(
                status_code=422, detail="Une VM ne se partage pas à son propre propriétaire"
            )
        if target not in ws_names:
            raise HTTPException(status_code=404, detail=f"Workspace {target!r} not found")
        desired.add(target)

    cfg = load_global()
    host_cfg = next((h for h in cfg.hosts if h.name == host_name), None)
    if host_cfg is None:
        raise HTTPException(status_code=404, detail=f"Host {host_name!r} not found")
    async with _get_engine().connect() as conn:
        if not await is_owned_test_host(login, ws, host_name, conn):
            raise HTTPException(
                status_code=404, detail=f"Test host {host_name!r} not owned by {ws!r}"
            )
        current = {t[0] for t in await list_shared_targets(login, host_name, conn)}

    node = node_for_host(cfg, host_cfg)
    to_add = desired - current
    to_remove = current - desired

    errors: list[str] = []
    if to_add:
        if node is None:
            raise HTTPException(
                status_code=409, detail="Nœud PVE de la VM introuvable — partage impossible"
            )
        for target in sorted(to_add):
            try:
                await add_share(login, ws, host_cfg, node, target)
            except ShareError as exc:
                errors.append(f"{target}: {exc}")
    for target in sorted(to_remove):
        await remove_share(login, host_cfg, node, target)

    if errors:
        raise HTTPException(status_code=502, detail="Partage partiel — " + " ; ".join(errors))

    async with _get_engine().connect() as conn:
        targets = await list_shared_targets(login, host_name, conn)
    return {"shared": sorted(t[0] for t in targets)}


# ─── Liens (clé → URL) d'un serveur de test (menu ⋮ du host) ─────────────────

_LINK_KEY_RE = re.compile(r"^[\w][\w .-]{0,49}$")


def _validate_link_url(url: str) -> None:
    """N'accepte que des URLs http(s) absolues — la valeur est ouverte par le navigateur."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=422, detail=f"URL http(s) absolue requise: {url!r}")


async def _require_ws_and_host(ws: str, host_name: str, login: str) -> None:
    if not _WS_NAME_RE.fullmatch(ws):
        raise HTTPException(status_code=422, detail="Invalid workspace name")
    if not _PROXMOX_NAME_RE.fullmatch(host_name):
        raise HTTPException(status_code=422, detail="Invalid host name")
    user_cfg = await load_user(login)
    if not any(w.name == ws for w in user_cfg.workspaces):
        raise HTTPException(status_code=404, detail=f"Workspace {ws!r} not found")


class TestHostLinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    url: str


@router.get("/workspaces/{ws}/test-hosts/{host_name}/links")
async def list_test_host_links_route(
    ws: str,
    host_name: str,
    user: UserInfo = Depends(require_user),
) -> list[dict[str, str]]:
    """Liens enregistrés pour un serveur de test du workspace."""
    await _require_ws_and_host(ws, host_name, user.login)
    async with _get_engine().connect() as conn:
        links = await list_test_host_links(user.login, ws, host_name, conn)
    if links is None:
        raise HTTPException(status_code=404, detail=f"Test host {host_name!r} not found")
    return links


@router.put("/workspaces/{ws}/test-hosts/{host_name}/links")
async def upsert_test_host_link_route(
    ws: str,
    host_name: str,
    body: TestHostLinkBody,
    user: UserInfo = Depends(require_user),
) -> dict[str, str]:
    """Enregistre (ou remplace) un lien clé → URL du serveur de test."""
    await _require_ws_and_host(ws, host_name, user.login)
    key = body.key.strip()
    if not _LINK_KEY_RE.fullmatch(key):
        raise HTTPException(status_code=422, detail=f"Invalid link key: {body.key!r}")
    url = body.url.strip()
    _validate_link_url(url)
    async with _get_engine().begin() as conn:
        saved = await upsert_test_host_link(user.login, ws, host_name, key, url, conn)
    if not saved:
        raise HTTPException(status_code=404, detail=f"Test host {host_name!r} not found")
    _log.info("test_host_link_saved", login=user.login, ws=ws, host=host_name, key=key)
    return {"key": key, "url": url}


@router.delete("/workspaces/{ws}/test-hosts/{host_name}/links/{key}", status_code=204)
async def delete_test_host_link_route(
    ws: str,
    host_name: str,
    key: str,
    user: UserInfo = Depends(require_user),
) -> None:
    """Supprime un lien du serveur de test."""
    await _require_ws_and_host(ws, host_name, user.login)
    async with _get_engine().begin() as conn:
        deleted = await delete_test_host_link(user.login, ws, host_name, key, conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Link {key!r} not found")
    _log.info("test_host_link_deleted", login=user.login, ws=ws, host=host_name, key=key)
