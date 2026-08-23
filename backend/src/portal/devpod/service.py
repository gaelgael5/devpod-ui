from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import structlog

from ..agents.keys import revoke_workspace_keys
from ..config.models import GitCredential, GlobalConfig, SourceSpec, WorkspaceSpec
from ..config.store import _data_root, load_global, load_user, safe_login_path, safe_user_path
from ..db.engine import _get_engine
from ..db.log_blobs import persist_log_blob_from_file
from ..db.workspace_status import (
    delete_status_db,
    fail_stale_provisioning_db,
    get_status_db,
    list_by_login_db,
    list_running_db,
    port_claimed_by_other_db,
    update_status_if_exists_db,
    upsert_status_db,
)
from ..events.bus import emit_event
from ..exposure import _WS_ID_RE
from ..messages import db as _msg_db
from ..profiles.models import Profile
from ..recipes.models import RecipeMeta
from .env import HostNotReadyError, _find_host, build_env, docker_cert_dir
from .provider import ensure_provider
from .runner import kill_if_running, run_subprocess
from .shelve import shelve_if_pending


async def _materialize_system_cert(slug: str, login: str = "") -> str:
    """Résout la clé privée PEM depuis harpo et l'écrit à un chemin STABLE.

    - Avec login : {user_devpod_dir}/keys/{slug}.pem — usage devpod workspace.
    - Sans login  : /data/keys/system/{slug}.pem — usage terminal admin host.

    Le chemin stable évite que ProxyCommand (devpod ssh --stdio) trouve une clé
    manquante après un rebuild du conteneur portail.
    """
    from ..certificates.pem import normalize_pem
    from ..secrets.system import reveal_system_cert

    async with _get_engine().begin() as conn:
        # Normalisation systématique : une clé importée/collée (CRLF Windows, newline
        # final manquant) ferait échouer ssh avec « error in libcrypto ». Répare aussi
        # les entrées déjà stockées sales, sans migration.
        pem = normalize_pem(await reveal_system_cert(slug, conn))

    if login:
        keys_dir = safe_user_path(login, "devpod") / "keys"
    else:
        keys_dir = _data_root() / "keys" / "system"
    keys_dir.mkdir(parents=True, exist_ok=True)
    path = keys_dir / f"{slug}.pem"
    # Écriture atomique — évite un état partiel si harpo est consulté en parallèle
    fd, tmp = tempfile.mkstemp(dir=keys_dir, suffix=".tmp")
    try:
        os.write(fd, pem.encode())
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return str(path)


if TYPE_CHECKING:
    from ..exposure import ExposureService

_log = structlog.get_logger(__name__)

# Redaction d'un éventuel `://user:secret@host` dans la sortie devpod avant de la
# logguer (défense en profondeur : le token vit normalement dans un fichier 0600,
# pas dans stdout, mais on ne prend pas le risque).
_REDACT_URL_CRED = re.compile(r"://([^:/@\s]+):[^@/\s]+@")


def _read_log_tail(path: Path, *, max_chars: int = 2000) -> str:
    """Dernières lignes d'un log devpod, redigées et aplaties en une ligne.

    Sert à rendre visible la cause d'un `devpod up` en échec (ex. `fatal:` du
    clone) directement dans structlog/Loki — le blob complet reste persisté à
    part. Best-effort : chaîne vide si le fichier est illisible.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = _REDACT_URL_CRED.sub(r"://\1:***@", text)
    tail = text[-max_chars:]
    return " | ".join(line for line in tail.splitlines() if line.strip())


# Verrous de lifecycle par ws_id (bug 003). Sérialisent TOUTE opération lifecycle
# (up/stop/delete + _run_up_task) sur un même workspace, contrairement au verrou de
# runner.py qui n'entoure que l'exécution du subprocess devpod. Ordre d'acquisition
# global : lifecycle → subprocess (jamais l'inverse), donc pas de cycle/deadlock.
# Registre module-level (comme runner._locks) : en prod la boucle est unique ; sous
# pytest-asyncio (une boucle par test) le registre est vidé entre tests via
# clear_lifecycle_locks (fixture autouse, cf. runner.clear_locks).
_lifecycle_locks: dict[str, asyncio.Lock] = {}


def _get_lifecycle_lock(ws_id: str) -> asyncio.Lock:
    return _lifecycle_locks.setdefault(ws_id, asyncio.Lock())


def clear_lifecycle_locks() -> None:
    """Vide le registre de verrous de lifecycle. Usage tests uniquement."""
    _lifecycle_locks.clear()


# Image de base utilisée quand aucune source git n'est fournie
_DEFAULT_IMAGE = "mcr.microsoft.com/devcontainers/base:ubuntu"

# Durée d'attente (secondes) après le lancement de devpod port-forward,
# pour laisser le tunnel SSH s'établir avant que Caddy tente de router.
_PORT_FORWARD_SETTLE_S = 3
# Port sur lequel DevPod démarre openvscode-server dans le devcontainer.
# DevPod 0.6.x utilise systématiquement 10800 (--port 10800 dans son agent).
_OPENVSCODE_SERVER_PORT = 10800


def _repo_name_from_url(url: str) -> str:
    """Dérive un nom de répertoire safe depuis une URL git."""
    base = url.rstrip("/").split("/")[-1]
    if base.endswith(".git"):
        base = base[:-4]
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", base)
    return safe or "repo"


_GITHUB_HTTPS_RE = re.compile(r"^https://github\.com/(?P<path>[^/]+/[^/]+?)(?:\.git)?/?$")


def _normalize_clone_url(url: str) -> str:
    """Convertit une URL GitHub HTTPS en SSH (git@) pour utiliser l'agent SSH forwardé.

    Évite le serveur git-credentials de devpod (panic v0.6.15) sur les dépôts privés.
    Les URLs non-GitHub ou déjà en git@ sont laissées inchangées.
    """
    m = _GITHUB_HTTPS_RE.match(url)
    if m:
        return f"git@github.com:{m.group('path')}.git"
    return url


def _reject_dash(url: str, branch: str) -> None:
    """Rejette une URL/branche commençant par '-' (argument injection git)."""
    if url.startswith("-"):
        raise ValueError(f"Source URL must not start with '-': {url!r}")
    if branch and branch.startswith("-"):
        raise ValueError(f"Branch must not start with '-': {branch!r}")


def _deferred_clone_command(url: str, branch: str, username: str, token: str) -> str:
    """Commande shell de clone post-readiness d'une source additionnelle en PAT HTTPS.

    L'auth passe par `http.extraHeader` (Authorization Basic), comme run_git_ls_remote :
    git n'émet jamais de requête credential, donc le serveur git-credentials de devpod
    (panic v0.6.15 en phase setup, workspace nil) n'est pas sollicité. Le token n'est ni
    dans l'URL clonée ni dans le remote enregistré — seulement dans l'en-tête HTTP.
    Idempotent : skip si la cible existe déjà (re-up de réconciliation).
    """
    from .git import _canonical_http_git_url

    canon = _canonical_http_git_url(url.strip())
    _reject_dash(canon, branch)
    target = f"/workspaces/{_repo_name_from_url(canon)}"
    b64 = base64.b64encode(f"{username}:{token}".encode()).decode()
    branch_arg = f"-b {shlex.quote(branch)} " if branch else ""
    return (
        f"if [ -e {shlex.quote(target)} ]; then exit 0; fi; "
        "GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false "
        f'git -c http.extraHeader="Authorization: Basic {b64}" '
        "-c credential.helper= "
        f"clone {branch_arg}-- {shlex.quote(canon)} {shlex.quote(target)}"
    )


def _deferred_ssh_clone_command(url: str, branch: str, key_pem: str) -> str:
    """Commande shell de clone post-readiness d'une source additionnelle via clé SSH.

    Pour une source authentifiée par un credential ssh sur un host ≠ source principale :
    l'agent SSH forwardé pendant `up` ne porte que la clé de la source principale. On
    matérialise donc la clé de déploiement dans un fichier 0600 éphémère du conteneur
    (effacé par `trap`, jamais loggé), et on l'utilise via `GIT_SSH_COMMAND`. Une URL
    https:// est convertie en `git@host:path` pour que la clé soit effective. Idempotent.
    """
    src = url.strip()
    _reject_dash(src, branch)
    parsed = urlparse(src)
    if parsed.scheme in ("https", "http"):
        ssh_url = f"git@{parsed.hostname}:{parsed.path.lstrip('/')}"
    else:
        ssh_url = src  # déjà git@host:path ou ssh://
    target = f"/workspaces/{_repo_name_from_url(ssh_url)}"
    branch_arg = f"-b {shlex.quote(branch)} " if branch else ""
    key_body = shlex.quote(key_pem.strip() + "\n")
    return (
        f"if [ -e {shlex.quote(target)} ]; then exit 0; fi; "
        'KF=$(mktemp); chmod 600 "$KF"; trap \'rm -f "$KF"\' EXIT; '
        f'printf %s {key_body} > "$KF"; '
        "GIT_TERMINAL_PROMPT=0 "
        'GIT_SSH_COMMAND="ssh -i $KF -o StrictHostKeyChecking=no -o BatchMode=yes" '
        f"git clone {branch_arg}-- {shlex.quote(ssh_url)} {shlex.quote(target)}"
    )


class DevPodService:
    def __init__(
        self,
        global_cfg: GlobalConfig,
        devpod_bin: list[str] | None = None,
        exposure: ExposureService | None = None,
    ) -> None:
        self._global_cfg = global_cfg
        self._devpod_bin: list[str] = (
            devpod_bin if devpod_bin is not None else [global_cfg.devpod.binary]
        )
        self._exposure = exposure
        self._background_tasks: set[asyncio.Task[None]] = set()
        # Tâches _run_up_task actives, indexées par ws_id : permettent à stop/delete
        # d'annuler un `up` en cours (politique delete-vs-up, bug 003).
        self._up_tasks: dict[str, asyncio.Task[None]] = {}
        # Processus devpod port-forward actifs, indexés par ws_id
        self._port_forward_procs: dict[str, asyncio.subprocess.Process] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def _ws_id(self, login: str, name: str) -> str:
        """Construit et valide le ws_id DNS-safe."""
        ws_id = f"{login}-{name}"
        if not _WS_ID_RE.fullmatch(ws_id):
            raise ValueError(f"Computed ws_id {ws_id!r} is not DNS-safe")
        return ws_id

    async def up(
        self,
        login: str,
        ws_spec: WorkspaceSpec,
        recipes: list[RecipeMeta] | None = None,
        feature_env: dict[str, str] | None = None,
        generate_ssh_key: bool = False,
        request_host: str = "",
        profile: Profile | None = None,
        lifecycle_event: str = "workspace.created",
    ) -> str:
        """Lance un workspace en tâche de fond. Retourne ws_id immédiatement.

        lifecycle_event : événement émis si le up aboutit — "workspace.created"
        par défaut, "workspace.restarted" quand l'appelant relance un workspace
        existant (restart/reconnect).
        """
        ws_id = self._ws_id(login, ws_spec.name)

        if generate_ssh_key:
            from ..db.ssh_keys import upsert_ssh_key_db
            from ..ssh_keys import ensure_workspace_ssh_key, get_workspace_ssh_key_path

            pub_key = await asyncio.to_thread(ensure_workspace_ssh_key, login, ws_spec.name)
            priv_path = get_workspace_ssh_key_path(login, ws_spec.name)
            async with _get_engine().begin() as _conn:
                await upsert_ssh_key_db(login, ws_spec.name, str(priv_path), pub_key, _conn)

        # Rechargement systématique : la liste des hosts évolue pendant la vie du singleton
        global_cfg = load_global()
        base_env = build_env(login=login, ws_spec=ws_spec, global_cfg=global_cfg)
        host_cfg = _find_host(ws_spec.host, global_cfg)

        if host_cfg.type == "ssh" and not host_cfg.host_cert_slug:
            raise HostNotReadyError(
                f"Host {host_cfg.name!r} : clé SSH manquante — lancez d'abord 'Configurer SSH'"
            )

        ssh_host = ""
        ssh_user = "root"
        if host_cfg.type == "ssh" and host_cfg.address:
            if "@" in host_cfg.address:
                ssh_user, ssh_host = host_cfg.address.split("@", 1)
            else:
                ssh_host = host_cfg.address

        tmp_key_path = ""
        task_created = False
        host_port: int | None = None
        ssh_port: int | None = None  # spec 18 T1 : port SSH publié sur l'IP du node
        ssh_pubkey: str | None = None
        # Initialisées AVANT le `try` : son `finally` les lit pour le nettoyage.
        # Placées à l'intérieur, elles restaient non liées si un `await` du début du
        # bloc échouait (cert système, provider, allocation de port, validation des
        # agents) — le `finally` levait alors un UnboundLocalError qui REMPLAÇAIT
        # l'erreur réelle et rendait l'échec indiagnosticable (reconnexions du 04/08).
        git_ssh_key_path = ""
        git_cred_home = ""  # HOME temporaire du credential store PAT (nettoyé après l'up)
        try:
            if host_cfg.type == "ssh" and host_cfg.host_cert_slug:
                tmp_key_path = await _materialize_system_cert(host_cfg.host_cert_slug, login)

            provider_name = await ensure_provider(
                login=login,
                host_type=host_cfg.type,
                env=base_env,
                host_name=host_cfg.name,
                ssh_host=ssh_host,
                ssh_user=ssh_user,
                ssh_key_path=tmp_key_path,
                devpod_bin=self._devpod_bin,
            )

            if self._exposure is not None:
                # Réutiliser le port déjà persisté pour ce ws_id (bug 001) : au re-up
                # (reconnexion, réconciliation au démarrage) une réallocation en rafale
                # sans mémoire partagée (_reserved volatile) produisait des collisions.
                # Jamais si un AUTRE workspace revendique le même port (doublon hérité
                # de l'ancienne allocation) : le réutiliser perpétuerait la collision —
                # on réalloue, et l'écriture provisioning ci-dessous assainit la ligne.
                reuse_port: int | None = None
                async with _get_engine().connect() as conn:
                    existing_row = await get_status_db(ws_id, conn)
                    raw_port = existing_row.get("host_port") if existing_row is not None else None
                    if raw_port is not None:
                        candidate = int(raw_port)
                        if await port_claimed_by_other_db(ws_id, candidate, conn):
                            _log.warning("port_duplicate_detected", ws_id=ws_id, port=candidate)
                        else:
                            reuse_port = candidate
                if reuse_port is not None:
                    host_port = reuse_port
                    _log.info("port_reused", ws_id=ws_id, port=host_port)
                else:
                    host_port = await self._exposure.allocate_port(ws_id)

                # Accès SSH par workspace (spec 18 T1, option A : le portail définit
                # toujours l'environnement en mode exposition). Port dédié (réutilisé
                # du même row au re-up, sinon alloué) + clé du workspace (idempotente,
                # générée avant le build pour être injectée dans authorized_keys).
                from ..bastion.provision import ensure_ws_ssh_pubkey

                raw_ssh = existing_row.get("ssh_port") if existing_row is not None else None
                ssh_port = (
                    int(raw_ssh)
                    if raw_ssh is not None
                    else await self._exposure.allocate_ssh_port(ws_id)
                )
                ssh_pubkey = await ensure_ws_ssh_pubkey(login, ws_id)

            # Spec 35b : validation des agents demandés (échec 422 si inconnu/
            # désactivé, host incompatible, ou external_url manquante). La LIVRAISON
            # des fichiers a lieu APRÈS readiness, par écriture directe dans le
            # conteneur (post-readiness dans _run_up_impl) : plus de bind mount, un
            # simple restart suffit à (ré)installer la config des agents.
            agent_ids: list[str] = []
            agents_mcp_url = ""
            if ws_spec.agents:
                from ..agents.provisioning import (
                    AgentProvisionError,
                    _load_requested_agent_types,
                )

                if host_cfg.type != "ssh":
                    raise AgentProvisionError(
                        f"agents non disponibles sur un host '{host_cfg.type}' "
                        "(dépose via devpod ssh, v1 SSH — spec 35 §10)"
                    )
                await _load_requested_agent_types(ws_spec.agents)  # 422 si invalide
                agents_mcp_url = global_cfg.server.external_url.rstrip("/") + "/mcp/"
                if not agents_mcp_url.startswith(("https://", "http://")):
                    raise AgentProvisionError(
                        "server.external_url doit être configurée pour exposer la "
                        "gateway MCP aux agents workspace"
                    )
                agent_ids = list(ws_spec.agents)

            # Sources additionnelles : celles authentifiées par PAT sont clonées
            # post-readiness (via ws_exec) pour éviter le panic du serveur git-credentials
            # de devpod (v0.6.15). Les autres restent dans le postCreateCommand.
            inline_sources, deferred_sources = await self._split_extra_sources(
                login, ws_spec.extra_sources
            )

            # Pour docker-tls : devcontainer.json généré localement, chemin absolu local valide.
            # Pour SSH : le fichier est généré localement puis uploadé sur la VM distante via
            #   tar|ssh avant devpod up ; le chemin absolu distant est passé à --devcontainer-path.
            dc_path: Path | None = None
            # Bornage mémoire (enabler 59864c37) : surcharge workspace, sinon
            # défaut global. "" = pas de limite.
            memory_limit = ws_spec.memory_limit or global_cfg.devpod.defaults.memory_limit
            needs_devcontainer = bool(
                recipes
                or feature_env
                or inline_sources
                or profile
                or ws_spec.recipe_volumes
                or memory_limit
                or ssh_port is not None  # spec 18 T1 : composant ssh-access injecté
            )
            if needs_devcontainer:
                # mkdtemp/copytree/write_text sont bloquants (plusieurs répertoires de
                # recettes à copier) : déportés hors de l'event loop (bug 039).
                dc_path = await asyncio.to_thread(
                    self._write_devcontainer,
                    login,
                    ws_id,
                    recipes=recipes,
                    feature_env=feature_env,
                    extra_sources=inline_sources or None,
                    profile=profile,
                    recipe_volumes=ws_spec.recipe_volumes or None,
                    memory_limit=memory_limit or None,
                    ssh_port=ssh_port,
                    ssh_pubkey=ssh_pubkey,
                    # Utilisateur du devcontainer (possède le socket tmux + reçoit
                    # authorized_keys) : image_user du profil si défini, sinon
                    # "vscode" (image de base devcontainer).
                    ws_user=(profile.image_user if profile is not None else "") or "vscode",
                )

            # Les env vars utilisateur (secrets) sont fusionnées ici, injectées dans
            # le subprocess env UNIQUEMENT — jamais dans devcontainer.json ni dans les logs.
            subprocess_env = {**base_env, **ws_spec.env}

            # Résolution du credential git pour l'injection dans devpod up.
            # On retire d'abord l'userinfo de l'URL (ex. Azure `org@dev.azure.com`) :
            # sinon git clone chercherait un credential pour l'utilisateur `org`,
            # que le credential store (username `oauth2`/`cred.username`) ne matche
            # pas → auth refusée. L'auth vient du credential injecté, pas de l'URL.
            effective_source = ws_spec.source
            if effective_source:
                from .git import strip_http_userinfo

                effective_source = strip_http_userinfo(effective_source)
            if ws_spec.git_credential and ws_spec.source:
                try:
                    user_cfg = await load_user(login)
                    cred = next(
                        (c for c in user_cfg.git_credentials if c.name == ws_spec.git_credential),
                        None,
                    )
                    if cred and cred.kind == "ssh" and cred.key_path:
                        git_ssh_key_path = cred.key_path
                        # DevPod ne supporte pas --git-token ; pour SSH on convertit l'URL
                        # en git@host:path afin que le forwarding SSH agent fonctionne.
                        if effective_source.startswith(("https://", "http://")):
                            parsed = urlparse(effective_source)
                            ssh_path = parsed.path.lstrip("/")
                            effective_source = f"git@{parsed.hostname}:{ssh_path}"
                            _log.info(
                                "devpod_source_converted_to_ssh",
                                login=login,
                                source=effective_source,
                            )
                    elif (
                        cred
                        and cred.kind == "token"
                        and cred.token
                        and effective_source.startswith(("https://", "http://"))
                    ):
                        # PAT HTTPS : devpod forwarde `git credential fill` au git côté
                        # portail lors du clone → on lui fournit le token via un store
                        # temporaire (l'URL reste HTTPS, pas de conversion SSH).
                        from .git import write_token_credential_store

                        host = urlparse(effective_source).hostname or cred.host
                        git_cred_home, cred_env = write_token_credential_store(
                            host, cred.username or "oauth2", cred.token
                        )
                        subprocess_env.update(cred_env)
                        _log.info("devpod_git_token_store_prepared", login=login, host=host)
                except Exception:
                    _log.warning("git_credential_lookup_failed", login=login, exc_info=True)

            # Combiner source et branche : "github.com/org/repo@feature-branch"
            # Sans source explicite, utiliser l'image de base pour que DevPod puisse
            # initialiser le workspace (sans source DevPod cherche un WS existant → erreur).
            devpod_source = effective_source or _DEFAULT_IMAGE
            if ws_spec.branch and effective_source:
                devpod_source = f"{effective_source}@{ws_spec.branch}"

            # Le tunnel openvscode (ssh -o ProxyCommand "devpod ssh --stdio") est
            # bindé sur 0.0.0.0:{host_port} DANS le conteneur portail pour tous les
            # types de host : l'upstream des routes Caddy / URLs est donc toujours
            # le portail, jamais le nœud (dont le pare-feu n'expose que 2376).
            node_ip = global_cfg.caddy.portal_host

            # Plusieurs sources → ouvrir /workspaces pour voir tous les repos clonés.
            # Source unique ou image seule → ouvrir directement /workspaces/{ws_id}.
            workspace_folder = "/workspaces" if ws_spec.extra_sources else f"/workspaces/{ws_id}"

            # Le host_port est persisté DÈS le provisioning (bug 001) : la colonne ne
            # repasse jamais à NULL pendant le devpod up (jusqu'à 30 min), donc
            # _used_ports() protège le port même après la perte de _reserved
            # (restart du portail, _reset_service).
            # ssh_port persisté dès le provisioning (comme host_port) : le registre
            # SSH le lit depuis workspace_status pour protéger le port durablement.
            await self._write_status(
                ws_id, "provisioning", login=login, host_port=host_port, ssh_port=ssh_port
            )

            task = asyncio.create_task(
                self._run_up_task(
                    ws_id,
                    devpod_source,
                    dc_path,
                    subprocess_env,
                    login,
                    host_port,
                    node_ip,
                    provider_name=provider_name,
                    host_type=host_cfg.type,
                    ssh_host=ssh_host,
                    ssh_user=ssh_user,
                    ssh_key_path=tmp_key_path,
                    request_host=request_host,
                    workspace_folder=workspace_folder,
                    host_name=host_cfg.name,
                    git_ssh_key_path=git_ssh_key_path,
                    git_cred_home=git_cred_home,
                    lifecycle_event=lifecycle_event,
                    agents=agent_ids,
                    mcp_url=agents_mcp_url,
                    project_root=f"/workspaces/{ws_id}",
                    deferred_sources=deferred_sources,
                )
            )
            self._background_tasks.add(task)
            self._up_tasks[ws_id] = task

            def _on_up_done(t: asyncio.Task[None]) -> None:
                self._background_tasks.discard(t)
                if self._up_tasks.get(ws_id) is t:
                    del self._up_tasks[ws_id]

            task.add_done_callback(_on_up_done)
            task_created = True
            _log.info("workspace_up_started", ws_id=ws_id, login=login)
            return ws_id
        finally:
            if not task_created and tmp_key_path and tmp_key_path.startswith(tempfile.gettempdir()):
                with contextlib.suppress(OSError):
                    os.unlink(tmp_key_path)
            if not task_created and git_cred_home:
                # La tâche n'a jamais démarré → son finally ne nettoiera pas le store.
                with contextlib.suppress(Exception):
                    shutil.rmtree(git_cred_home, ignore_errors=True)
            if not task_created and host_port is not None and self._exposure is not None:
                # Le port a été réservé en mémoire (allocate_port) mais _run_up_task
                # n'a jamais démarré : jamais persisté en DB, il faut le relâcher
                # explicitement (bug 037), sinon il reste réservé jusqu'au restart.
                await self._exposure.release_port(host_port)
            if not task_created and ssh_port is not None and self._exposure is not None:
                await self._exposure.release_ssh_port(ssh_port)

    def _devpod_state_exists(self, ws_id: str, login: str) -> bool:
        """Vérifie si devpod connaît ce workspace (état local présent).

        Le state devpod est dans DEVPOD_HOME = safe_user_path(login, 'devpod'),
        pas dans $HOME/.devpod — $HOME est le HOME système du conteneur.
        """
        devpod_home = str(safe_user_path(login, "devpod"))
        return Path(f"{devpod_home}/agent/contexts/default/workspaces/{ws_id}").exists()

    async def _reconnect_workspace(self, ws_id: str, login: str) -> None:
        """Re-enregistre un workspace dans devpod via devpod up.

        Appelé quand l'état devpod est absent au démarrage (rebuild conteneur portail
        sans volume mount). DevPod détecte le container existant sur l'hôte distant
        et se reconnecte sans le recréer. Le port-forward est relancé en fin de up().

        Délègue à start_existing_workspace : la résolution recettes/secrets/profil
        doit être rejouée — un up() nu (recipes=None) ne régénère pas le
        devcontainer.json et devpod échoue sur le chemin uploadé de la fois
        précédente, supprimé après chaque up.
        """
        # Import différé : routes → service à l'import du module, jamais l'inverse.
        from ..routes.workspace_ops import start_existing_workspace

        try:
            ws_name = ws_id.removeprefix(f"{login}-")
            _log.info("reconcile_triggering_devpod_up", ws_id=ws_id, login=login)
            async with _get_engine().connect() as conn:
                await start_existing_workspace(login, ws_name, conn)
        except ValueError:
            _log.warning("reconcile_ws_spec_not_found", ws_id=ws_id, login=login)
        except Exception as exc:
            # exc_info : sans le traceback, un échec de reconnexion n'est pas
            # diagnosticable a posteriori — `str(exc)` seul avait laissé les
            # reconnexions du 04/08 sans cause identifiable.
            _log.warning(
                "reconcile_reconnect_failed",
                ws_id=ws_id,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )

    async def fail_stale_provisioning(self) -> None:
        """Au démarrage : bascule en `failed` les lignes `provisioning` orphelines.

        La transition provisioning → running/failed est écrite exclusivement par
        la tâche asyncio du `devpod up` (_run_up_task), qui meurt avec le process.
        Après un restart, toute ligne encore `provisioning` est donc orpheline et
        resterait bloquée à vie sans ce balayage.
        """
        async with _get_engine().begin() as conn:
            failed_ids = await fail_stale_provisioning_db(conn)
        if failed_ids:
            _log.warning("stale_provisioning_failed", ws_ids=failed_ids, count=len(failed_ids))

    async def reconcile_port_forwards(self) -> None:
        """Au démarrage, relance les tunnels SSH et recrée les routes Caddy des workspaces running.

        Si le conteneur portail redémarre :
        - État devpod présent  → relance le tunnel SSH directement + recrée la route Caddy.
        - État devpod absent   → déclenche devpod up en arrière-plan ; devpod
          détecte le container existant, se reconnecte et relance le tunnel en fin de up().
        """
        global_cfg = load_global()
        async with _get_engine().connect() as conn:
            running_rows = await list_running_db(conn)
        for data in running_rows:
            ws_id: str = data.get("ws_id", "")
            host_port_raw = data.get("host_port")
            host_name: str = data.get("host_name", "")
            login_for_key: str = data.get("login", "") or ws_id.split("-")[0]
            if not ws_id or host_port_raw is None:
                continue
            host_port = int(host_port_raw)

            # Si devpod ne connaît pas ce workspace, relancer devpod up
            # qui re-peuplera ~/.devpod/ et relancera le port-forward en fin de tâche.
            if not self._devpod_state_exists(ws_id, login_for_key):
                _log.warning(
                    "reconcile_devpod_state_missing",
                    ws_id=ws_id,
                    msg="devpod up déclenché en arrière-plan pour reconnexion automatique",
                )
                task = asyncio.create_task(self._reconnect_workspace(ws_id, login_for_key))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
                continue

            try:
                host_cfg = _find_host(host_name, global_cfg)
            except Exception:
                _log.warning("reconcile_host_not_found", ws_id=ws_id, host_name=host_name)
                continue
            _log.info("reconcile_port_forward", ws_id=ws_id, host_port=host_port)
            # Env complet requis : sans DEVPOD_HOME, `devpod ssh --stdio` cherche le
            # workspace dans le contexte par défaut → "workspace doesn't exist" et le
            # tunnel meurt silencieusement. DOCKER_* requis pour les hosts docker-tls.
            tunnel_env = {
                "HOME": os.environ.get("HOME", "/root"),
                "PATH": os.environ.get("PATH", ""),
                "DEVPOD_HOME": str(safe_user_path(login_for_key, "devpod")),
            }
            if host_cfg.type == "docker-tls":
                tunnel_env["DOCKER_HOST"] = host_cfg.docker_host
                tunnel_env["DOCKER_TLS_VERIFY"] = "1"
                tunnel_env["DOCKER_CERT_PATH"] = docker_cert_dir(host_cfg, global_cfg)
            tmp_key_path = ""
            pf_ok = False
            try:
                if host_cfg.host_cert_slug:
                    tmp_key_path = await _materialize_system_cert(
                        host_cfg.host_cert_slug, login_for_key
                    )
                await self._start_port_forward(
                    ws_id,
                    tunnel_env,
                    host_port,
                )
                pf_ok = True
            except Exception as exc:
                _log.warning("reconcile_port_forward_failed", ws_id=ws_id, error=str(exc))
            finally:
                if tmp_key_path and tmp_key_path.startswith(tempfile.gettempdir()):
                    with contextlib.suppress(OSError):
                        os.unlink(tmp_key_path)

            if pf_ok and self._exposure is not None:
                # Le tunnel est bindé sur le container portal (tous types de host) ;
                # Caddy atteint portal_host:host_port via le réseau Docker interne.
                node_ip = global_cfg.caddy.portal_host
                try:
                    await self._exposure.expose(ws_id, node_ip, host_port)
                    _log.info("reconcile_caddy_route_restored", ws_id=ws_id)
                except Exception as exc:
                    _log.warning("reconcile_expose_failed", ws_id=ws_id, error=str(exc))

    def reconnect(self, login: str, ws_id: str) -> None:
        """Reconnexion forcée d'un workspace dont le conteneur tourne (portal_reload, modèle a).

        Lance la reconnexion (devpod up détecte le container existant et relance le
        tunnel) en arrière-plan et rend la main immédiatement. Référencée dans
        _background_tasks (comme up()) : une tâche non référencée peut être
        ramassée par le GC avant son terme, perdant silencieusement la reconnexion.
        """
        task = asyncio.create_task(self._reconnect_workspace(ws_id, login))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _cancel_up_task(self, ws_id: str) -> None:
        """Annule un `up` en cours pour ws_id et attend sa terminaison (bug 003).

        Politique delete/stop-vs-up : on ANNULE le provisioning en cours plutôt que
        d'attendre (jusqu'à 30 min) une provision qu'on va détruire/arrêter. On tue
        aussi le subprocess devpod (kill_if_running) pour débloquer `run_subprocess`,
        puis on attend la fin de la tâche : cela garantit que le verrou lifecycle est
        relâché AVANT que l'appelant tente de l'acquérir.
        """
        await kill_if_running(ws_id)
        task = self._up_tasks.get(ws_id)
        if task is None or task.done():
            return
        task.cancel()
        # CancelledError est une BaseException : le `except Exception` de _run_up_impl
        # ne l'intercepte pas, la tâche remonte l'annulation, exécute ses finally
        # (nettoyage) et relâche le verrou lifecycle. On avale l'annulation ici : c'est
        # NOUS qui l'avons déclenchée, elle ne doit pas annuler stop/delete.
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            _log.warning("up_task_ended_with_error_during_cancel", ws_id=ws_id)
        _log.info("up_task_cancelled", ws_id=ws_id)

    async def stop(self, login: str, ws_id: str) -> None:
        """Arrête un workspace en cours d'exécution."""
        # Annule un `up` en cours (le subprocess est tué) puis sérialise via le verrou
        # lifecycle : stop ne peut pas s'entrelacer avec un provisioning (bug 003).
        await self._cancel_up_task(ws_id)
        async with _get_lifecycle_lock(ws_id):
            await self._stop_port_forward(ws_id)
            if self._exposure is not None:
                try:
                    await self._exposure.unexpose(ws_id)
                except Exception as exc:
                    _log.warning("workspace_unexpose_failed", ws_id=ws_id, error=type(exc).__name__)
            env = self._minimal_env(login)
            cmd = [*self._devpod_bin, "stop", ws_id]
            log_path = self._log_path(login, f"{ws_id}-stop")
            rc = await run_subprocess(
                cmd=cmd, env=env, log_path=log_path, ws_id=ws_id, timeout_s=120
            )
            async with _get_engine().begin() as _conn:
                await persist_log_blob_from_file(ws_id, login, "stop", log_path, _conn)
            # Écritures gardées (épitaphe, bug 007) : stop() sur un workspace dont la
            # ligne a été supprimée (delete concurrent ou antérieur) ne doit jamais
            # recréer une ligne fantôme — seul up() crée la ligne (provisioning).
            if rc != 0:
                # L'exposition est déjà retirée (tunnel + route Caddy) ; si `devpod stop`
                # échoue, le conteneur peut encore tourner — ne jamais mentir en écrivant
                # "stopped" : l'état réel est indéterminé tant qu'on n'a pas reconfirmé.
                _log.warning("workspace_stop_failed", ws_id=ws_id, returncode=rc)
                await self._write_status_if_exists(ws_id, "unknown", login=login)
                return
            await self._write_status_if_exists(ws_id, "stopped", login=login)
            _log.info("workspace_stopped", ws_id=ws_id, login=login)
            from ..db.user_config import owner_identity_subject

            await emit_event(
                "workspace.stopped",
                actor=login,
                workspace=ws_id.removeprefix(f"{login}-"),
                subject={**await owner_identity_subject(login), "ws_id": ws_id},
            )
            # Nettoyage Termix au stop (spec 18 T5) : le host node_ip:ssh_port devient
            # injoignable → on retire host+credential côté Termix, mais on GARDE la clé
            # SSH (purge_state=False) pour un restart propre. Best-effort.
            from ..bastion import provision as _bastion

            try:
                if _bastion.enabled():
                    await _bastion.deprovision_workspace(login, ws_id, purge_state=False)
            except Exception:
                _log.warning("bastion_deprovision_on_stop_failed", ws_id=ws_id, exc_info=True)

    async def delete(self, login: str, ws_id: str, *, shelve: bool = True) -> dict[str, Any]:
        """Supprime un workspace (force). Shelve le travail en attente si shelve=True."""
        # Annule un `up` en cours (provisioning) et tue son subprocess, puis prend le
        # verrou lifecycle pour toute la suppression : aucune écriture de statut tardive
        # de _run_up_task ne peut s'entrelacer avec delete_status_db (bug 003).
        await self._cancel_up_task(ws_id)
        async with _get_lifecycle_lock(ws_id):
            branch: str | None = None
            if shelve:
                # Jamais de shelve sur un workspace en provisioning (bug 041) : l'up
                # vient d'être tué, `devpod ssh` sur un conteneur à moitié provisionné
                # échouerait en 409 et laisserait un zombie non nettoyé. Pour les autres
                # statuts, un échec de shelve annule la suppression AVANT tout démontage
                # (le workspace reste intact et utilisable).
                async with _get_engine().connect() as conn:
                    row = await get_status_db(ws_id, conn)
                status = row["status"] if row is not None else None
                if status in (None, "provisioning"):
                    _log.info("workspace_shelve_skipped", ws_id=ws_id, status=status or "absent")
                else:
                    # shelve_if_pending lance devpod ssh (git dans le conteneur), pas une
                    # opération lifecycle DevPod — hors du verrou subprocess de run_subprocess.
                    branch = await shelve_if_pending(
                        self._devpod_bin, ws_id, self._minimal_env(login)
                    )
            await self._stop_port_forward(ws_id)
            if self._exposure is not None:
                try:
                    await self._exposure.unexpose(ws_id)
                except Exception as exc:
                    _log.warning("workspace_unexpose_failed", ws_id=ws_id, error=type(exc).__name__)
            env = self._minimal_env(login)
            cmd = [*self._devpod_bin, "delete", ws_id, "--force"]
            log_path = self._log_path(login, f"{ws_id}-delete")
            rc = await run_subprocess(
                cmd=cmd, env=env, log_path=log_path, ws_id=ws_id, timeout_s=120
            )
            if rc != 0:
                _log.warning("workspace_delete_failed", ws_id=ws_id, returncode=rc)
            ws_name = ws_id.removeprefix(f"{login}-")
            async with _get_engine().begin() as conn:
                await persist_log_blob_from_file(ws_id, login, "delete", log_path, conn)
                await delete_status_db(ws_id, conn)
                await _msg_db.purge_workspace_messages(conn, login, ws_name)
                # Spec 35 : les clefs MCP du workspace meurent avec lui.
                await revoke_workspace_keys(conn, login, ws_id)
            await self._purge_agent_config(login, ws_id, ws_name)
            _log.info("workspace_deleted", ws_id=ws_id, login=login, recovery_branch=branch)
            from ..db.user_config import owner_identity_subject

            await emit_event(
                "workspace.deleted",
                actor=login,
                workspace=ws_name,
                subject={
                    **await owner_identity_subject(login),
                    "ws_id": ws_id,
                    "recovery_branch": branch,
                },
            )
            # Déprovision Termix DIRECTE (spec 18 T5) — pas via automate : retire
            # host + credential sur toutes les instances + le secret d'état.
            # Best-effort : jamais bloquant pour la suppression.
            from ..bastion import provision as _bastion

            try:
                if _bastion.enabled():
                    await _bastion.deprovision_workspace(login, ws_id)
            except Exception:
                _log.warning("bastion_deprovision_on_delete_failed", ws_id=ws_id, exc_info=True)
            return {"deleted": True, "recovery_branch": branch}

    async def _purge_agent_config(self, login: str, ws_id: str, ws_name: str) -> None:
        """Purge best-effort de l'arborescence agent-config sur le host (spec 35).

        Les clefs sont déjà révoquées en DB (fail closed) : un échec de purge ne
        laisse que des fichiers inertes sur un host admin-only — best-effort assumé.
        """
        try:
            user_cfg = await load_user(login)
            spec = next((w for w in user_cfg.workspaces if w.name == ws_name), None)
            if spec is None or not spec.agents:
                return
            host_cfg = _find_host(spec.host, load_global())
            if host_cfg.type != "ssh" or not (host_cfg.address and host_cfg.host_cert_slug):
                return
            ssh_user, ssh_host = "root", host_cfg.address
            if "@" in host_cfg.address:
                ssh_user, ssh_host = host_cfg.address.split("@", 1)
            key_path = await _materialize_system_cert(host_cfg.host_cert_slug, login)
            from ..agents.sync import purge_tree_ssh

            await purge_tree_ssh(ws_id, ssh_user=ssh_user, ssh_host=ssh_host, ssh_key_path=key_path)
        except Exception:
            _log.warning("agent_config_purge_failed", ws_id=ws_id, exc_info=True)

    async def status(self, login: str, ws_id: str) -> dict[str, Any]:
        """Retourne l'état courant depuis la DB."""
        async with _get_engine().connect() as conn:
            row = await get_status_db(ws_id, conn)
        if row is None:
            return {"ws_id": ws_id, "status": "unknown"}
        return {k: v for k, v in row.items() if v is not None or k in ("ws_id", "status", "login")}

    async def list_workspaces(self, login: str) -> list[dict[str, Any]]:
        """Liste les workspaces du user depuis la DB."""
        async with _get_engine().connect() as conn:
            rows = await list_by_login_db(login, conn)
        return [{k: v for k, v in r.items() if v is not None} for r in rows]

    async def get_port(self, ws_id: str) -> int | None:
        """Retourne le port hôte alloué depuis la DB."""
        async with _get_engine().connect() as conn:
            row = await get_status_db(ws_id, conn)
        if row is None:
            return None
        p = row.get("host_port")
        return int(p) if p is not None else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_path(self, login: str, ws_id: str) -> Path:
        return safe_login_path("logs", login, f"{ws_id}.log")

    async def _write_status(self, ws_id: str, status: str, login: str = "", **extra: Any) -> None:
        """Persiste le statut du workspace en DB (upsert : crée la ligne si absente)."""
        async with _get_engine().begin() as conn:
            await upsert_status_db(ws_id, status, conn, login=login, **extra)

    async def _write_status_if_exists(
        self, ws_id: str, status: str, login: str = "", **extra: Any
    ) -> bool:
        """Écrit le statut UNIQUEMENT si la ligne existe encore (épitaphe, bug 003).

        Utilisé pour les écritures FINALES de _run_up_task : si un delete concurrent a
        supprimé la ligne, l'UPDATE atomique WHERE ws_id ne touche rien et ne ressuscite
        pas le workspace — même si upsert_status_db reste un upsert inconditionnel.
        Retourne True si la ligne a été mise à jour.
        """
        async with _get_engine().begin() as conn:
            written = await update_status_if_exists_db(ws_id, status, conn, login=login, **extra)
        if not written:
            _log.warning("workspace_status_write_skipped_deleted", ws_id=ws_id, status=status)
        return written

    def _write_devcontainer(
        self,
        login: str,
        ws_id: str,
        recipes: list[RecipeMeta] | None = None,
        feature_env: dict[str, str] | None = None,
        extra_sources: list[SourceSpec] | None = None,
        profile: Profile | None = None,
        recipe_volumes: list[str] | None = None,
        extra_mounts: list[str] | None = None,
        extra_post_create: list[str] | None = None,
        memory_limit: str | None = None,
        ssh_port: int | None = None,
        ssh_pubkey: str | None = None,
        ws_user: str = "vscode",
    ) -> Path:
        """Écrit devcontainer.json + Feature dirs dans un tmpdir. Retourne le chemin du JSON."""
        user_dir = safe_user_path(login, "devpod")
        user_dir.mkdir(parents=True, exist_ok=True)

        tmp_dir = Path(tempfile.mkdtemp(dir=user_dir, prefix=f"{ws_id}-dc-"))
        try:
            # Image de base : celle du profil si définie (image outillée — les
            # recettes ne couvrent alors que les manques), sinon le défaut portail.
            base_image = profile.image if profile is not None and profile.image else _DEFAULT_IMAGE
            content: dict[str, Any] = {"image": base_image}

            if recipes:
                key_to_id: dict[str, str] = {r.key: r.id for r in recipes}
                features_block: dict[str, dict[str, Any]] = {}
                for recipe in recipes:
                    recipe_dir = _data_root() / "recipes" / recipe.id
                    if not recipe_dir.is_dir():
                        _log.warning(
                            "recipe_dir_missing_skip",
                            recipe_id=recipe.id,
                            path=str(recipe_dir),
                        )
                        continue
                    dest = tmp_dir / recipe.id
                    shutil.copytree(recipe_dir, dest)
                    # Réécrire installsAfter avec les IDs locaux réels
                    # (les fichiers sur le serveur peuvent pointer vers des IDs
                    # de registry comme ghcr.io/... qui ne correspondent pas
                    # aux features locales ./nodejs)
                    feature_json = dest / "devcontainer-feature.json"
                    if feature_json.exists() and recipe.installs_after:
                        dep_ids = [key_to_id[k] for k in recipe.installs_after if k in key_to_id]
                        if dep_ids:
                            fd: dict[str, Any] = json.loads(
                                feature_json.read_text(encoding="utf-8")
                            )
                            fd["installsAfter"] = [f"./{d}" for d in dep_ids]
                            feature_json.write_text(json.dumps(fd, indent=2), encoding="utf-8")
                    features_block[f"./{recipe.id}"] = {}
                if features_block:
                    content["features"] = features_block

            if feature_env:
                content["remoteEnv"] = dict(feature_env)

            if extra_sources:
                clone_cmds: list[str] = []
                for src in extra_sources:
                    url = src.url.strip()
                    if not url:
                        continue
                    # Défense en profondeur : rejeter les valeurs commençant par '-'
                    # même si la route les valide déjà (argument injection git).
                    if url.startswith("-"):
                        raise ValueError(f"Source URL must not start with '-': {url!r}")
                    if src.branch and src.branch.startswith("-"):
                        raise ValueError(f"Branch must not start with '-': {src.branch!r}")
                    url = _normalize_clone_url(url)
                    repo_name = _repo_name_from_url(url)
                    target = f"/workspaces/{repo_name}"
                    # Désactive le credential helper de devpod : sur un dépôt HTTPS
                    # exigeant une auth, git interrogerait le serveur git-credentials
                    # de devpod qui panique en phase setup (workspace nil, v0.6.15) et
                    # ferait échouer TOUT le workspace. Avec askpass=/bin/false +
                    # credential.helper vide, git échoue proprement (auth refusée) sans
                    # jamais solliciter ce tunnel. Inerte pour les URLs ssh (git@).
                    prefix = (
                        "GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false git -c credential.helper="
                    )
                    # '--' empêche git d'interpréter l'URL comme un flag.
                    if src.branch:
                        clone_cmds.append(
                            f"{prefix} clone -b {shlex.quote(src.branch)} -- "
                            f"{shlex.quote(url)} {shlex.quote(target)}"
                        )
                    else:
                        clone_cmds.append(
                            f"{prefix} clone -- {shlex.quote(url)} {shlex.quote(target)}"
                        )
                if clone_cmds:
                    content["postCreateCommand"] = " && ".join(clone_cmds)

            # Spec 35 : symlinks agent-config après les clones éventuels.
            if extra_post_create:
                existing_pc = content.get("postCreateCommand")
                parts = [existing_pc] if existing_pc else []
                content["postCreateCommand"] = " && ".join([*parts, *extra_post_create])

            if profile is not None:
                frag = profile.to_customizations()["vscode"]
                if frag["extensions"] or frag["settings"]:
                    vscode = content.setdefault("customizations", {}).setdefault("vscode", {})
                    existing = vscode.get("extensions") or []
                    vscode["extensions"] = list(dict.fromkeys([*existing, *frag["extensions"]]))
                    vscode["settings"] = {
                        **(vscode.get("settings") or {}),
                        **frag["settings"],
                    }

            # Bornage mémoire (enabler 59864c37) : un agent emballé tue SON
            # conteneur, pas le host. runArgs vérifié contre devpod v0.6.15
            # (struct devcontainer config) ; appliqué à la (re)construction.
            if memory_limit:
                content["runArgs"] = [f"--memory={memory_limit}"]

            # Composants système (spec 18 T1) : accès SSH par workspace publié sur
            # l'IP du node. Injecté quand une clé + un port SSH sont fournis (mode
            # exposition). AJOUTE features/runArgs (--publish)/postStartCommand (sshd).
            if ssh_port is not None and ssh_pubkey:
                from ..wscomponents.devcontainer import inject_components

                inject_components(
                    content,
                    tmp_dir,
                    {"ssh_port": str(ssh_port), "ssh_pubkey": ssh_pubkey, "ws_user": ws_user},
                )

            mounts: list[str] = []
            if recipe_volumes and recipes:
                for recipe in recipes:
                    if recipe.memory_volume is not None and recipe.id in recipe_volumes:
                        vol_name = f"{ws_id}-{recipe.memory_volume.name}"
                        mounts.append(
                            f"source={vol_name},"
                            f"target={recipe.memory_volume.mapping.target},"
                            f"type=volume"
                        )
            if extra_mounts:
                mounts.extend(extra_mounts)
            if mounts:
                content["mounts"] = mounts

            dc_path = tmp_dir / "devcontainer.json"
            dc_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
            return dc_path
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    async def _upload_devcontainer_to_ssh(
        self,
        dc_dir: Path,
        ws_id: str,
        ssh_user: str,
        ssh_host: str,
        ssh_key_path: str,
    ) -> tuple[str, str]:
        """Upload devcontainer.json + features sur la VM SSH via tar|ssh.

        Le répertoire de workspace DevPod est effacé puis recréé à chaque
        'devpod up' sur un workspace existant (message 'Delete old workspace').
        On uploade donc dans {home}/.devpod-portal-dc/{ws_id}/ — hors du
        workspace DevPod — et on passe le chemin absolu à --devcontainer-path.

        Retourne (absolute_devcontainer_path, remote_dir) :
        - absolute_devcontainer_path : chemin absolu à passer à --devcontainer-path
        - remote_dir : chemin absolu distant pour le nettoyage post-up

        Lève RuntimeError si l'upload échoue.
        """
        ssh_opts = [
            "-i",
            ssh_key_path,
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
        ]
        ssh_target = f"{ssh_user}@{ssh_host}"

        # Récupérer le home dir réel de l'utilisateur SSH
        home_proc = await asyncio.create_subprocess_exec(
            "ssh",
            *ssh_opts,
            ssh_target,
            "echo $HOME",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        home_out, _ = await home_proc.communicate()
        home = home_out.decode().strip() or f"/home/{ssh_user}"

        # DevPod fait filepath.Join(content_dir, devcontainer_path) en Go :
        # les chemins absolus sont traités comme relatifs (le '/' initial est ignoré).
        # Un chemin relatif '../../.devpod-portal-dc/{ws_id}/' depuis content/ résout
        # vers workspaces/.devpod-portal-dc/{ws_id}/ — répertoire FRÈRE du workspace
        # DevPod, donc non effacé lors du "Delete old workspace {ws_id}".
        # content/ est toujours à depth 2 sous workspaces/ : workspaces/{ws_id}/content/
        devpod_workspaces = f"{home}/.devpod/agent/contexts/default/workspaces"
        remote_dir = f"{devpod_workspaces}/.devpod-portal-dc/{ws_id}"
        devcontainer_path = f"../../.devpod-portal-dc/{ws_id}/devcontainer.json"

        remote_cmd = f"mkdir -p {shlex.quote(remote_dir)} && tar xzf - -C {shlex.quote(remote_dir)}"

        tar_proc = await asyncio.create_subprocess_exec(
            "tar",
            "czf",
            "-",
            "-C",
            str(dc_dir),
            ".",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        ssh_proc = await asyncio.create_subprocess_exec(
            "ssh",
            *ssh_opts,
            ssh_target,
            remote_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _pump() -> None:
            assert tar_proc.stdout is not None
            assert ssh_proc.stdin is not None
            try:
                # drain() DANS la boucle : backpressure réel (sinon tout le tar
                # est bufferisé en mémoire avant la première écriture réseau).
                while chunk := await tar_proc.stdout.read(65536):
                    ssh_proc.stdin.write(chunk)
                    await ssh_proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError, RuntimeError):
                # ssh mort ou stdin fermé pendant l'écriture : on arrête de
                # pomper sans lever — l'échec réel est rapporté par le
                # returncode ssh ci-dessous (avec son stderr). On DRAINE alors
                # tar jusqu'à EOF pour le laisser se terminer : sans lecteur il
                # bloquerait sur son pipe plein, et un kill() laisserait un
                # zombie que Process.wait() d'asyncio ne récolte pas (pipe
                # stdout non consommé) — vérifié : wait() pendait indéfiniment.
                with contextlib.suppress(Exception):
                    while await tar_proc.stdout.read(65536):
                        pass
            finally:
                with contextlib.suppress(Exception):
                    ssh_proc.stdin.close()

        # PAS de ssh_proc.communicate() ici : communicate() sans input ferme
        # immédiatement stdin, en pleine course avec le pump qui y écrit —
        # flux tronqué (« gzip: unexpected end of file » côté distant) et
        # RuntimeError « handler is closed » côté portail (bug vu au boot).
        pump_task = asyncio.create_task(_pump())
        assert ssh_proc.stderr is not None
        ssh_err = await ssh_proc.stderr.read()
        await pump_task
        await ssh_proc.wait()
        await tar_proc.wait()

        # ssh d'abord : si le pump a avorté (ssh mort), tar a été tué (-9) et
        # son returncode ne doit pas masquer l'erreur ssh réelle (avec stderr).
        if ssh_proc.returncode != 0:
            raise RuntimeError(
                f"Upload SSH devcontainer vers {remote_dir!r} échoué : "
                f"{ssh_err.decode(errors='replace').strip()}"
            )
        if tar_proc.returncode != 0:
            raise RuntimeError(f"tar devcontainer échoué (code {tar_proc.returncode})")
        _log.info("devcontainer_uploaded_ssh", remote_dir=remote_dir, path=devcontainer_path)
        return devcontainer_path, remote_dir

    async def _cleanup_ssh_dir(
        self,
        remote_dir: str,
        ssh_user: str,
        ssh_host: str,
        ssh_key_path: str,
    ) -> None:
        """Supprime le répertoire temporaire distant après devpod up (best-effort)."""
        ssh_opts = [
            "-i",
            ssh_key_path,
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
        ]
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            *ssh_opts,
            f"{ssh_user}@{ssh_host}",
            f"rm -rf {shlex.quote(remote_dir)}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

    def _minimal_env(self, login: str) -> dict[str, str]:
        """Env minimal pour les commandes stop/delete (pas de secrets)."""
        return {
            "PATH": os.environ.get("PATH", ""),
            "DEVPOD_HOME": str(safe_user_path(login, "devpod")),
        }

    async def _start_port_forward(
        self,
        ws_id: str,
        env: dict[str, str],
        host_port: int,
    ) -> None:
        """
        Expose le port 3000 du devcontainer via le tunnel SSH écrit par DevPod.
        Après devpod up, DevPod écrit une entrée `{ws_id}.devpod` dans
        /root/.ssh/config avec un ProxyCommand vers le container (docker exec).
        ssh(1) standard crée un vrai listener local via -L, contrairement à
        `devpod ssh -L` qui ne bind pas de socket.
        """
        # ProxyCommand explicite : ne dépend pas de l'entrée ~/.ssh/config écrite
        # par DevPod, qui est perdue au rebuild du conteneur portail.
        if ws_id.startswith("-"):
            raise ValueError(f"Insecure ws_id: {ws_id!r}")
        # Re-up/reconcile : tuer un éventuel tunnel précédent de ce workspace,
        # sinon l'ancien processus garde le port et le nouveau bind échoue.
        await self._stop_port_forward(ws_id)
        proxy_cmd = f"{shlex.join(self._devpod_bin)} ssh --stdio {shlex.quote(ws_id)}"
        cmd = [
            "ssh",
            "-N",
            "-o",
            f"ProxyCommand={proxy_cmd}",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            # Bind raté (port déjà pris) → ssh doit mourir, pas continuer sans
            # forward : le check post-spawn le détecte alors comme une erreur.
            "-o",
            "ExitOnForwardFailure=yes",
            "-L",
            f"0.0.0.0:{host_port}:localhost:{_OPENVSCODE_SERVER_PORT}",
            "root@devpod-ws",
        ]
        ssh_env = {**env, "HOME": os.environ.get("HOME", "/root")}
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=ssh_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._port_forward_procs[ws_id] = proc
        # Laisser le tunnel SSH s'établir avant que Caddy tente de router
        await asyncio.sleep(_PORT_FORWARD_SETTLE_S)
        # Un tunnel qui meurt immédiatement (workspace inconnu, daemon injoignable…)
        # doit être une erreur visible, pas un listener fantôme.
        if proc.returncode is not None:
            stderr_txt = ""
            if proc.stderr is not None:
                with contextlib.suppress(Exception):
                    stderr_txt = (await proc.stderr.read()).decode(errors="replace")
            self._port_forward_procs.pop(ws_id, None)
            _log.error(
                "port_forward_died",
                ws_id=ws_id,
                host_port=host_port,
                returncode=proc.returncode,
                stderr=stderr_txt[-500:],
            )
            raise RuntimeError(f"port-forward {ws_id} died: {stderr_txt[-200:]}")
        _log.info("port_forward_started", ws_id=ws_id, host_port=host_port)

    async def _stop_port_forward(self, ws_id: str) -> None:
        """Arrête le processus devpod port-forward s'il est en cours (best-effort)."""
        proc = self._port_forward_procs.pop(ws_id, None)
        if proc is None:
            return
        if proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=5.0)
        _log.info("port_forward_stopped", ws_id=ws_id)

    async def _split_extra_sources(
        self, login: str, extra_sources: list[SourceSpec]
    ) -> tuple[list[SourceSpec], list[tuple[SourceSpec, GitCredential]]]:
        """Répartit les sources additionnelles : clone in-devcontainer vs post-readiness.

        Une source AUTHENTIFIÉE (credential token OU ssh résolu) est différée : son clone
        a lieu post-readiness via ws_exec, hors du tunnel git-credentials de devpod qui
        panique en phase setup (v0.6.15) et sans dépendre de l'agent SSH forwardé (qui ne
        porte que la clé de la source principale). Les sources publiques restent inline.
        """
        if not extra_sources:
            return [], []
        user_cfg = await load_user(login)
        by_name = {c.name: c for c in user_cfg.git_credentials}
        inline: list[SourceSpec] = []
        deferred: list[tuple[SourceSpec, GitCredential]] = []
        for src in extra_sources:
            cred = by_name.get(src.git_credential) if src.git_credential else None
            usable = cred is not None and (
                (cred.kind == "token" and bool(cred.token))
                or (cred.kind == "ssh" and bool(cred.key_path))
            )
            if usable and cred is not None:
                deferred.append((src, cred))
            else:
                inline.append(src)
        return inline, deferred

    async def _clone_deferred_sources(
        self, login: str, ws_id: str, deferred: list[tuple[SourceSpec, GitCredential]]
    ) -> None:
        """Clone les sources additionnelles authentifiées (token ou ssh), post-readiness.

        Best-effort : un échec laisse le workspace `running` et est logué (rc seul, jamais
        le token, la clé ni la sortie git). Voir _deferred_clone_command /
        _deferred_ssh_clone_command pour le contournement du panic devpod."""
        from .exec import ws_exec

        for src, cred in deferred:
            repo = _repo_name_from_url(src.url.strip())
            try:
                command = await self._build_deferred_command(src, cred)
            except (ValueError, OSError):
                _log.warning("extra_source_clone_rejected", ws_id=ws_id, repo=repo, exc_info=True)
                continue
            try:
                rc, _out = await ws_exec(login, ws_id, command, timeout=300.0)
            except Exception:
                _log.warning("extra_source_clone_failed", ws_id=ws_id, repo=repo, exc_info=True)
                continue
            if rc == 0:
                _log.info("extra_source_cloned", ws_id=ws_id, repo=repo)
            else:
                _log.warning("extra_source_clone_rc", ws_id=ws_id, repo=repo, rc=rc)

    async def _build_deferred_command(self, src: SourceSpec, cred: GitCredential) -> str:
        """Construit la commande de clone post-readiness selon le type de credential."""
        if cred.kind == "ssh":
            key_pem = await asyncio.to_thread(Path(cred.key_path).read_text, encoding="utf-8")
            return _deferred_ssh_clone_command(src.url, src.branch, key_pem)
        return _deferred_clone_command(src.url, src.branch, cred.username or "oauth2", cred.token)

    async def _push_agent_files_safe(
        self, login: str, ws_id: str, agents: list[str], mcp_url: str, project_root: str
    ) -> None:
        """Écrit la config des agents dans le conteneur (post-readiness, best-effort).

        Un échec (canal, home introuvable, rendu) n'invalide pas le workspace, qui
        reste `running` : il est logué. La révocation au décochage d'un profil reste
        gérée séparément (fail-closed)."""
        from ..agents.push import push_agent_files

        try:
            pushed = await push_agent_files(
                login=login,
                ws_id=ws_id,
                ws_name=ws_id.removeprefix(f"{login}-"),
                agents=agents,
                mcp_url=mcp_url,
                project_root=project_root,
            )
            _log.info("agent_files_pushed_on_up", ws_id=ws_id, agents=pushed)
        except Exception:
            _log.warning("agent_files_push_failed", ws_id=ws_id, exc_info=True)

    async def _run_up_task(self, ws_id: str, *args: Any, **kwargs: Any) -> None:
        """Tâche de fond `up`, sérialisée par le verrou lifecycle par ws_id (bug 003).

        Le verrou est détenu pour TOUTE la durée de l'orchestration (subprocess devpod +
        allocation port-forward + expose + écriture de statut), pas seulement le
        subprocess. Un stop/delete concurrent annule cette tâche (kill + task.cancel),
        la libération du verrou intervient alors dans les finally de _run_up_impl.
        """
        async with _get_lifecycle_lock(ws_id):
            await self._run_up_impl(ws_id, *args, **kwargs)

    async def _run_up_impl(
        self,
        ws_id: str,
        source: str,
        dc_path: Path | None,
        env: dict[str, str],
        login: str,
        host_port: int | None = None,
        node_ip: str = "127.0.0.1",
        provider_name: str = "",
        host_type: str = "",
        ssh_host: str = "",
        ssh_user: str = "root",
        ssh_key_path: str = "",
        request_host: str = "",
        workspace_folder: str = "",
        host_name: str = "",
        git_ssh_key_path: str = "",
        git_cred_home: str = "",
        lifecycle_event: str = "workspace.created",
        agents: list[str] | None = None,
        mcp_url: str = "",
        project_root: str = "",
        deferred_sources: list[tuple[SourceSpec, GitCredential]] | None = None,
    ) -> None:
        """Exécute devpod up, expose le workspace si running. Détient déjà le verrou."""
        # Copie de l'env pour y injecter SSH_AUTH_SOCK sans muter le dict partagé
        subprocess_env = dict(env)
        agent_proc: asyncio.subprocess.Process | None = None

        # Pour les providers SSH avec credential git SSH : démarrer un ssh-agent
        # temporaire, y charger la clé deploy, et exposer SSH_AUTH_SOCK au subprocess
        # devpod. Le provider est configuré avec -A (ForwardAgent) dans EXTRA_FLAGS,
        # ce qui transmet l'agent à la VM distante pour que git clone puisse s'authentifier.
        #
        # -D (foreground) au lieu de -s seul : sans -D, `ssh-agent -s` daemonise —
        # le process lancé imprime les variables d'env PUIS SORT IMMÉDIATEMENT (vérifié
        # empiriquement), le vrai agent tournant en arrière-plan sous un PID différent,
        # jamais capturé. Avec -D, agent_proc reste le process réel de l'agent tout du
        # long : agent_proc.pid est le vrai PID (pas de fork), et on peut le tuer dans le
        # finally indépendamment du succès du parsing de sa sortie (bug 038).
        if git_ssh_key_path and host_type == "ssh":
            try:
                agent_proc = await asyncio.create_subprocess_exec(
                    "ssh-agent",
                    "-s",
                    "-D",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                assert agent_proc.stdout is not None
                first_line = await agent_proc.stdout.readline()
                sock_match = re.search(
                    r"SSH_AUTH_SOCK=([^;]+);", first_line.decode(errors="replace")
                )
                if sock_match:
                    subprocess_env["SSH_AUTH_SOCK"] = sock_match.group(1)
                    subprocess_env["SSH_AGENT_PID"] = str(agent_proc.pid)
                    add_proc = await asyncio.create_subprocess_exec(
                        "ssh-add",
                        git_ssh_key_path,
                        env=subprocess_env,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, add_err = await add_proc.communicate()
                    if add_proc.returncode != 0:
                        _log.warning(
                            "git_ssh_add_failed",
                            ws_id=ws_id,
                            error=add_err.decode(errors="replace").strip(),
                        )
                    else:
                        _log.info("git_ssh_agent_started", ws_id=ws_id)
                else:
                    _log.warning(
                        "git_ssh_agent_output_unparsable",
                        ws_id=ws_id,
                        output=first_line.decode(errors="replace"),
                    )
            except Exception:
                _log.warning("git_ssh_agent_setup_failed", ws_id=ws_id, exc_info=True)

        # Pour SSH : uploader le devcontainer sur la VM distante avant devpod up.
        remote_dc_dir: str | None = None
        remote_dc_json: str | None = None
        if host_type == "ssh" and dc_path is not None and ssh_host and ssh_key_path:
            try:
                remote_dc_json, remote_dc_dir = await self._upload_devcontainer_to_ssh(
                    dc_path.parent, ws_id, ssh_user, ssh_host, ssh_key_path
                )
            except Exception:
                _log.warning("devcontainer_upload_ssh_failed", ws_id=ws_id, exc_info=True)

        try:
            cmd = [
                *self._devpod_bin,
                "--debug",
                "up",
                "--id",
                ws_id,
                "--ide",
                "openvscode",
                "--open-ide=false",  # v0.6.15 : empêche l'ouverture auto du navigateur
            ]
            if host_type == "ssh" and remote_dc_json:
                cmd += ["--devcontainer-path", remote_dc_json]
            elif host_type != "ssh" and dc_path is not None:
                cmd += ["--devcontainer-path", str(dc_path)]
            if provider_name:
                cmd += ["--provider", provider_name]
            if source:
                cmd += [
                    "--",  # fin des flags — défense en profondeur contre l'injection argv
                    source,
                ]
            log_path = self._log_path(login, ws_id)
            # Seul le returncode est logué — la valeur des env vars (secrets) n'est jamais écrite
            returncode = await run_subprocess(
                cmd=cmd, env=subprocess_env, log_path=log_path, ws_id=ws_id, timeout_s=1800
            )
            async with _get_engine().begin() as _conn:
                await persist_log_blob_from_file(ws_id, login, "up", log_path, _conn)
            status = "running" if returncode == 0 else "failed"
            extra: dict[str, Any] = {
                "returncode": returncode,
                "host_type": host_type,
                "host_name": host_name,
            }

            # Tunnel openvscode pour TOUS les types de host : `devpod ssh --stdio`
            # est agnostique du provider (docker exec via daemon TLS pour docker-tls,
            # ssh pour les VMs). Le port n'est jamais publié sur le nœud.
            if status == "running" and host_port is not None:
                try:
                    await self._start_port_forward(ws_id, env, host_port)
                except Exception:
                    # Workspace démarré mais tunnel KO : on garde le statut running,
                    # l'erreur est loguée (le proxy VS Code répondra 502/503).
                    _log.error("port_forward_start_failed", ws_id=ws_id, exc_info=True)

            if status == "running" and self._exposure is not None and host_port is not None:
                extra["host_port"] = host_port
                try:
                    url = await self._exposure.expose(
                        ws_id=ws_id,
                        node_ip=node_ip,
                        host_port=host_port,
                        request_host=request_host,
                        workspace_folder=workspace_folder,
                    )
                    extra["url"] = url
                except Exception as exc:
                    _log.error(
                        "workspace_expose_failed",
                        ws_id=ws_id,
                        error=type(exc).__name__,
                    )
            elif host_port is not None:
                extra["host_port"] = host_port
            # Écriture FINALE gardée (épitaphe) : ne ressuscite pas une ligne qu'un
            # delete concurrent aurait supprimée (bug 003).
            await self._write_status_if_exists(ws_id, status, login=login, **extra)
            if returncode != 0:
                # Tail de la sortie devpod (clone/build) pour ne plus être aveugle
                # sur un up qui plante — le blob complet reste persisté par ailleurs.
                output_tail = await asyncio.to_thread(_read_log_tail, log_path)
                _log.warning(
                    "workspace_up_failed",
                    ws_id=ws_id,
                    returncode=returncode,
                    output_tail=output_tail,
                )
            else:
                _log.info("workspace_up_done", ws_id=ws_id, login=login)
                # Le `up` vient d'appliquer le profil : l'utilisateur du conteneur a
                # pu changer (image_user). On oublie la valeur cachée AVANT toute
                # opération post-readiness, qui passe par ws_exec sous cet utilisateur.
                from .ws_user import invalidate as _invalidate_ws_user

                _invalidate_ws_user(ws_id)
                # Sources additionnelles en PAT : clonées ici, conteneur prêt (ws_exec
                # joignable), hors du tunnel git-credentials devpod qui panique en setup.
                if deferred_sources:
                    await self._clone_deferred_sources(login, ws_id, deferred_sources)
                # Spec 35b : livraison des fichiers agents PAR ÉCRITURE conteneur,
                # une fois le conteneur prêt (ws_exec joignable). Aucun bind mount,
                # aucun recreate — rejoué à chaque up, donc un restart suffit.
                if agents:
                    await self._push_agent_files_safe(login, ws_id, agents, mcp_url, project_root)
                # ForceCommand ssh-access (spec 18 T1) rafraîchie à chaque up (spec
                # 35b) : les workspaces existants prennent la version courante au
                # restart, sans recreate. Gatée dans la commande sur la présence du
                # script (no-op hors T1). Best-effort : jamais bloquant.
                try:
                    from ..wscomponents.registry import tmux_attach_refresh_cmd
                    from .exec import ws_exec

                    rc, out = await ws_exec(login, ws_id, tmux_attach_refresh_cmd())
                    if rc != 0:
                        _log.warning(
                            "ws_tmux_attach_refresh_failed", ws_id=ws_id, rc=rc, output=out[-300:]
                        )
                except Exception:
                    _log.warning("ws_tmux_attach_refresh_crashed", ws_id=ws_id, exc_info=True)
                # Clé SSH du workspace rafraîchie à chaque up (même motif) : le hash
                # de prebuild devpod ignore le contenu des features → une image en
                # cache peut porter une clé périmée après un delete/recreate (le
                # delete purge l'état, le up regénère une clé neuve). Gatée dans la
                # commande sur le sshd_config du composant (no-op hors T1).
                # Best-effort : jamais bloquant.
                try:
                    from ..bastion.provision import ensure_ws_ssh_pubkey, resolve_ws_user
                    from ..wscomponents.registry import authorized_keys_refresh_cmd
                    from .exec import ws_exec

                    pubkey = await ensure_ws_ssh_pubkey(login, ws_id)
                    # Foyer cible = celui de ws_user (image_user du profil) : ws_exec
                    # demande toujours `vscode`, donc $HOME n'est PAS le bon foyer
                    # quand le profil définit un autre utilisateur.
                    ws_user = await resolve_ws_user(login, ws_id)
                    rc, out = await ws_exec(
                        login, ws_id, authorized_keys_refresh_cmd(pubkey, ws_user)
                    )
                    if rc != 0:
                        _log.warning(
                            "ws_authorized_keys_refresh_failed",
                            ws_id=ws_id,
                            rc=rc,
                            output=out[-300:],
                        )
                except Exception:
                    _log.warning("ws_authorized_keys_refresh_crashed", ws_id=ws_id, exc_info=True)
                from ..db.user_config import owner_identity_subject

                await emit_event(
                    lifecycle_event,
                    actor=login,
                    workspace=ws_id.removeprefix(f"{login}-"),
                    subject={
                        **await owner_identity_subject(login),
                        "ws_id": ws_id,
                        "node": host_name,
                    },
                )
                # Provisioning Termix DIRECT (spec 18 T5) — pas via automate (couplage
                # assumé) : au up réussi, (re)crée + partage le host node_ip:ssh_port
                # sur les instances des accessors. Best-effort : jamais bloquant.
                from ..bastion import provision as _bastion

                try:
                    if _bastion.enabled():
                        await _bastion.provision_workspace(login, ws_id)
                except Exception:
                    _log.warning("bastion_provision_on_up_failed", ws_id=ws_id, exc_info=True)
        except Exception as exc:
            await self._write_status_if_exists(
                ws_id, "failed", login=login, error=type(exc).__name__
            )
            _log.error("workspace_up_crashed", ws_id=ws_id, error=type(exc).__name__)
            if host_port is not None and self._exposure is not None:
                # Ce chemin de crash n'écrit pas host_port dans workspace_status
                # (contrairement au chemin returncode != 0 plus haut) : jamais
                # persisté, le port reste réservé en mémoire tant qu'il n'est pas
                # relâché explicitement (bug 037).
                await self._exposure.release_port(host_port)
        finally:
            if dc_path is not None:
                with contextlib.suppress(Exception):
                    shutil.rmtree(dc_path.parent, ignore_errors=True)
            if remote_dc_dir and ssh_host and ssh_key_path:
                with contextlib.suppress(Exception):
                    await self._cleanup_ssh_dir(remote_dc_dir, ssh_user, ssh_host, ssh_key_path)
            if agent_proc is not None and agent_proc.returncode is None:
                # Tue le process ssh-agent -D directement — indépendamment du succès
                # du parsing de sa sortie (bug 038) : agent_proc est le process réel
                # (foreground), pas un lanceur déjà sorti après avoir daemonisé.
                with contextlib.suppress(ProcessLookupError):
                    agent_proc.kill()
                with contextlib.suppress(Exception):
                    await agent_proc.wait()
                _log.info("git_ssh_agent_stopped", ws_id=ws_id)
            if ssh_key_path and ssh_key_path.startswith(tempfile.gettempdir()):
                with contextlib.suppress(OSError):
                    os.unlink(ssh_key_path)
            if git_cred_home and git_cred_home.startswith(tempfile.gettempdir()):
                # Store PAT temporaire : supprimé quoi qu'il arrive (le token ne
                # survit jamais au clone).
                with contextlib.suppress(Exception):
                    shutil.rmtree(git_cred_home, ignore_errors=True)
