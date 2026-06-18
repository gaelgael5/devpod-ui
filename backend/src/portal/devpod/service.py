from __future__ import annotations

import asyncio
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

from ..config.models import GlobalConfig, SourceSpec, WorkspaceSpec
from ..config.store import _data_root, load_global, load_user, safe_user_path
from ..db.engine import _get_engine
from ..db.log_blobs import persist_log_blob_from_file
from ..db.workspace_status import (
    delete_status_db,
    get_status_db,
    list_by_login_db,
    list_running_db,
    upsert_status_db,
)
from ..profiles.models import Profile
from ..recipes.models import RecipeMeta
from .env import HostNotReadyError, _find_host, build_env
from .provider import ensure_provider
from .runner import run_subprocess
from .shelve import shelve_if_pending

if TYPE_CHECKING:
    from ..exposure import ExposureService

_log = structlog.get_logger(__name__)

# DNS-safe pour ws_id : login (max ~40 chars) + "-" + name (max 32 chars)
_WS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")

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
    ) -> str:
        """Lance un workspace en tâche de fond. Retourne ws_id immédiatement."""
        ws_id = self._ws_id(login, ws_spec.name)

        if generate_ssh_key:
            from ..db.ssh_keys import upsert_ssh_key_db
            from ..ssh_keys import ensure_workspace_ssh_key, get_workspace_ssh_key_path

            pub_key = await asyncio.to_thread(ensure_workspace_ssh_key, login, ws_spec.name)
            priv_path = get_workspace_ssh_key_path(login, ws_spec.name)
            async with _get_engine().begin() as _conn:
                await upsert_ssh_key_db(
                    login, ws_spec.name, str(priv_path), pub_key, _conn
                )

        # Rechargement systématique : la liste des hosts évolue pendant la vie du singleton
        global_cfg = load_global()
        base_env = build_env(login=login, ws_spec=ws_spec, global_cfg=global_cfg)
        host_cfg = _find_host(ws_spec.host, global_cfg)

        if host_cfg.type == "ssh" and not host_cfg.key_path:
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

        provider_name = await ensure_provider(
            login=login,
            host_type=host_cfg.type,
            env=base_env,
            host_name=host_cfg.name,
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            ssh_key_path=host_cfg.key_path,
            devpod_bin=self._devpod_bin,
        )

        host_port: int | None = None
        if self._exposure is not None:
            host_port = await self._exposure.allocate_port(ws_id)

        # Pour docker-tls : devcontainer.json généré localement, chemin absolu local valide.
        # Pour SSH : l'agent DevPod tourne sur la VM distante. --devcontainer-path y est
        #   résolu relativement à content/ → un chemin local au portail est inexploitable.
        #   On utilise devpod ssh -L après devpod up pour exposer le port 3000
        #   du container sur le portail, et Caddy route vers portal:{host_port}.
        dc_path: Path | None = None
        if host_cfg.type == "docker-tls":
            dc_path = self._write_devcontainer(
                login,
                ws_id,
                host_port=host_port,
                recipes=recipes,
                feature_env=feature_env,
                extra_sources=ws_spec.extra_sources if ws_spec.extra_sources else None,
                profile=profile,
            )

        # Les env vars utilisateur (secrets) sont fusionnées ici, injectées dans
        # le subprocess env UNIQUEMENT — jamais dans devcontainer.json ni dans les logs.
        subprocess_env = {**base_env, **ws_spec.env}

        # Résolution du credential git pour l'injection dans devpod up
        git_ssh_key_path = ""
        effective_source = ws_spec.source
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
            except Exception:
                _log.warning("git_credential_lookup_failed", login=login, exc_info=True)

        # Combiner source et branche : "github.com/org/repo@feature-branch"
        # Sans source explicite, utiliser l'image de base pour que DevPod puisse
        # initialiser le workspace (sans source DevPod cherche un WS existant → erreur).
        devpod_source = effective_source or _DEFAULT_IMAGE
        if ws_spec.branch and effective_source:
            devpod_source = f"{effective_source}@{ws_spec.branch}"

        # Pour SSH : devpod ssh -L bind sur 0.0.0.0 dans le container portal ;
        # Caddy atteint portal:{host_port} via le réseau Docker interne.
        # Pour docker-tls : l'IP réelle du nœud Docker est utilisée directement.
        node_ip = self._resolve_node_ip(host_cfg)
        if host_cfg.type == "ssh":
            node_ip = global_cfg.caddy.portal_host

        # Plusieurs sources → ouvrir /workspaces pour voir tous les repos clonés.
        # Source unique ou image seule → ouvrir directement /workspaces/{ws_id}.
        workspace_folder = "/workspaces" if ws_spec.extra_sources else f"/workspaces/{ws_id}"

        await self._write_status(ws_id, "provisioning", login=login)

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
                ssh_key_path=host_cfg.key_path or "",
                request_host=request_host,
                workspace_folder=workspace_folder,
                host_name=host_cfg.name,
                git_ssh_key_path=git_ssh_key_path,
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        _log.info("workspace_up_started", ws_id=ws_id, login=login)
        return ws_id

    async def reconcile_port_forwards(self) -> None:
        """Au démarrage, relance les tunnels SSH des workspaces running persistés en DB.

        Si le container portal redémarre, les process ssh -L sont perdus mais le devcontainer
        reste actif sur le nœud distant.  Cette méthode relit workspace_status et rétablit
        les tunnels manquants sans relancer devpod up.
        """
        global_cfg = load_global()
        minimal_env = {"HOME": os.environ.get("HOME", "/root")}
        async with _get_engine().connect() as conn:
            running_rows = await list_running_db(conn)
        for data in running_rows:
            if data.get("host_type") != "ssh":
                continue
            ws_id: str = data.get("ws_id", "")
            host_port_raw = data.get("host_port")
            host_name: str = data.get("host_name", "")
            if not ws_id or host_port_raw is None:
                continue
            host_port = int(host_port_raw)
            try:
                host_cfg = _find_host(host_name, global_cfg)
            except Exception:
                _log.warning("reconcile_host_not_found", ws_id=ws_id, host_name=host_name)
                continue
            ssh_user, ssh_host = "root", ""
            if host_cfg.address:
                if "@" in host_cfg.address:
                    ssh_user, ssh_host = host_cfg.address.split("@", 1)
                else:
                    ssh_host = host_cfg.address
            _log.info("reconcile_port_forward", ws_id=ws_id, host_port=host_port)
            try:
                await self._start_port_forward(
                    ws_id,
                    minimal_env,
                    host_port,
                    ssh_host=ssh_host,
                    ssh_user=ssh_user,
                    ssh_key_path=host_cfg.key_path or "",
                )
            except Exception as exc:
                _log.warning("reconcile_port_forward_failed", ws_id=ws_id, error=str(exc))

    async def stop(self, login: str, ws_id: str) -> None:
        """Arrête un workspace en cours d'exécution."""
        await self._stop_port_forward(ws_id)
        if self._exposure is not None:
            try:
                await self._exposure.unexpose(ws_id)
            except Exception as exc:
                _log.warning("workspace_unexpose_failed", ws_id=ws_id, error=type(exc).__name__)
        env = self._minimal_env(login)
        cmd = [*self._devpod_bin, "stop", ws_id]
        log_path = self._log_path(login, f"{ws_id}-stop")
        await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id)
        async with _get_engine().begin() as _conn:
            await persist_log_blob_from_file(ws_id, login, "stop", log_path, _conn)
        await self._write_status(ws_id, "stopped", login=login)
        _log.info("workspace_stopped", ws_id=ws_id, login=login)

    async def delete(self, login: str, ws_id: str, *, shelve: bool = True) -> dict[str, Any]:
        """Supprime un workspace (force). Shelve le travail en attente si shelve=True."""
        branch: str | None = None
        if shelve:
            # shelve_if_pending lance devpod ssh (git dans le conteneur), pas une opération
            # lifecycle DevPod — intentionnellement en dehors du verrou workspace de run_subprocess.
            branch = await shelve_if_pending(self._devpod_bin, ws_id, self._minimal_env(login))
        await self._stop_port_forward(ws_id)
        if self._exposure is not None:
            try:
                await self._exposure.unexpose(ws_id)
            except Exception as exc:
                _log.warning("workspace_unexpose_failed", ws_id=ws_id, error=type(exc).__name__)
        env = self._minimal_env(login)
        cmd = [*self._devpod_bin, "delete", ws_id, "--force"]
        log_path = self._log_path(login, f"{ws_id}-delete")
        rc = await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id)
        if rc != 0:
            _log.warning("workspace_delete_failed", ws_id=ws_id, returncode=rc)
        async with _get_engine().begin() as conn:
            await persist_log_blob_from_file(ws_id, login, "delete", log_path, conn)
            await delete_status_db(ws_id, conn)
        _log.info("workspace_deleted", ws_id=ws_id, login=login, recovery_branch=branch)
        return {"deleted": True, "recovery_branch": branch}

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
        return _data_root() / "logs" / login / f"{ws_id}.log"

    async def _write_status(self, ws_id: str, status: str, login: str = "", **extra: Any) -> None:
        """Persiste le statut du workspace en DB."""
        async with _get_engine().begin() as conn:
            await upsert_status_db(ws_id, status, conn, login=login, **extra)

    def _write_devcontainer(
        self,
        login: str,
        ws_id: str,
        host_port: int | None = None,
        recipes: list[RecipeMeta] | None = None,
        feature_env: dict[str, str] | None = None,
        extra_sources: list[SourceSpec] | None = None,
        profile: Profile | None = None,
    ) -> Path:
        """Écrit devcontainer.json + Feature dirs dans un tmpdir. Retourne le chemin du JSON."""
        user_dir = safe_user_path(login, "devpod")
        user_dir.mkdir(parents=True, exist_ok=True)

        tmp_dir = Path(tempfile.mkdtemp(dir=user_dir, prefix=f"{ws_id}-dc-"))
        try:
            content: dict[str, Any] = {
                "image": "mcr.microsoft.com/devcontainers/base:ubuntu",
            }
            if host_port is not None:
                content["appPorts"] = [f"{host_port}:{_OPENVSCODE_SERVER_PORT}"]

            if recipes:
                features_block: dict[str, dict[str, Any]] = {}
                for recipe in recipes:
                    recipe_dir = _data_root() / "recipes" / recipe.id
                    if recipe_dir.is_dir():
                        shutil.copytree(recipe_dir, tmp_dir / recipe.id)
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
                    repo_name = _repo_name_from_url(url)
                    target = f"/workspaces/{repo_name}"
                    # '--' empêche git d'interpréter l'URL comme un flag.
                    if src.branch:
                        clone_cmds.append(
                            f"git clone -b {shlex.quote(src.branch)} -- "
                            f"{shlex.quote(url)} {shlex.quote(target)}"
                        )
                    else:
                        clone_cmds.append(f"git clone -- {shlex.quote(url)} {shlex.quote(target)}")
                if clone_cmds:
                    content["postCreateCommand"] = " && ".join(clone_cmds)

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

            dc_path = tmp_dir / "devcontainer.json"
            dc_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
            return dc_path
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def _resolve_node_ip(self, host_cfg: Any) -> str:
        """Résout l'IP du nœud Docker/SSH depuis l'HostConfig."""
        from ..config.models import HostConfig

        if not isinstance(host_cfg, HostConfig):
            return "127.0.0.1"
        if host_cfg.type == "docker-tls" and host_cfg.docker_host:
            return urlparse(host_cfg.docker_host).hostname or "127.0.0.1"
        if host_cfg.type == "ssh" and host_cfg.address:
            addr = host_cfg.address
            if "@" in addr:
                _, addr = addr.split("@", 1)
            return addr.strip() or "127.0.0.1"
        return "127.0.0.1"

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
        ssh_host: str = "",
        ssh_user: str = "root",
        ssh_key_path: str = "",
    ) -> None:
        """
        Expose le port 3000 du devcontainer via le tunnel SSH écrit par DevPod.
        Après devpod up, DevPod écrit une entrée `{ws_id}.devpod` dans
        /root/.ssh/config avec un ProxyCommand vers le container (docker exec).
        ssh(1) standard crée un vrai listener local via -L, contrairement à
        `devpod ssh -L` qui ne bind pas de socket.
        """
        # HOME est requis pour que ssh(1) trouve /root/.ssh/config écrit par DevPod.
        ssh_env = {**env, "HOME": os.environ.get("HOME", "/root")}
        cmd = [
            "ssh",
            "-N",
            "-L",
            f"0.0.0.0:{host_port}:localhost:{_OPENVSCODE_SERVER_PORT}",
            f"{ws_id}.devpod",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=ssh_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._port_forward_procs[ws_id] = proc
        _log.info("port_forward_started", ws_id=ws_id, host_port=host_port)
        # Laisser le tunnel SSH s'établir avant que Caddy tente de router
        await asyncio.sleep(_PORT_FORWARD_SETTLE_S)

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

    async def _run_up_task(
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
    ) -> None:
        """Tâche de fond : exécute devpod up, expose le workspace si running."""
        # Copie de l'env pour y injecter SSH_AUTH_SOCK sans muter le dict partagé
        subprocess_env = dict(env)
        agent_pid: str | None = None

        # Pour les providers SSH avec credential git SSH : démarrer un ssh-agent
        # temporaire, y charger la clé deploy, et exposer SSH_AUTH_SOCK au subprocess
        # devpod. Le provider est configuré avec -A (ForwardAgent) dans EXTRA_FLAGS,
        # ce qui transmet l'agent à la VM distante pour que git clone puisse s'authentifier.
        if git_ssh_key_path and host_type == "ssh":
            try:
                agent_proc = await asyncio.create_subprocess_exec(
                    "ssh-agent", "-s",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                agent_stdout, _ = await agent_proc.communicate()
                agent_output = agent_stdout.decode(errors="replace")
                sock_match = re.search(r"SSH_AUTH_SOCK=([^;]+);", agent_output)
                pid_match = re.search(r"SSH_AGENT_PID=(\d+);", agent_output)
                if sock_match and pid_match:
                    subprocess_env["SSH_AUTH_SOCK"] = sock_match.group(1)
                    subprocess_env["SSH_AGENT_PID"] = pid_match.group(1)
                    agent_pid = pid_match.group(1)
                    add_proc = await asyncio.create_subprocess_exec(
                        "ssh-add", git_ssh_key_path,
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
            except Exception:
                _log.warning("git_ssh_agent_setup_failed", ws_id=ws_id, exc_info=True)

        try:
            cmd = [
                *self._devpod_bin,
                "up",
                "--id",
                ws_id,
                "--ide",
                "openvscode",
                "--open-ide=false",  # v0.6.15 : empêche l'ouverture auto du navigateur
            ]
            if dc_path is not None:
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
                cmd=cmd, env=subprocess_env, log_path=log_path, ws_id=ws_id
            )
            async with _get_engine().begin() as _conn:
                await persist_log_blob_from_file(ws_id, login, "up", log_path, _conn)
            status = "running" if returncode == 0 else "failed"
            extra: dict[str, Any] = {
                "returncode": returncode,
                "host_type": host_type,
                "host_name": host_name,
            }

            if status == "running" and host_type == "ssh" and host_port is not None:
                await self._start_port_forward(
                    ws_id,
                    env,
                    host_port,
                    ssh_host=ssh_host,
                    ssh_user=ssh_user,
                    ssh_key_path=ssh_key_path,
                )

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
            await self._write_status(ws_id, status, login=login, **extra)
            if returncode != 0:
                _log.warning("workspace_up_failed", ws_id=ws_id, returncode=returncode)
            else:
                _log.info("workspace_up_done", ws_id=ws_id, login=login)
        except Exception as exc:
            await self._write_status(ws_id, "failed", login=login, error=type(exc).__name__)
            _log.error("workspace_up_crashed", ws_id=ws_id, error=type(exc).__name__)
        finally:
            if dc_path is not None:
                with contextlib.suppress(Exception):
                    shutil.rmtree(dc_path.parent, ignore_errors=True)
            if agent_pid:
                with contextlib.suppress(Exception):
                    kill_proc = await asyncio.create_subprocess_exec(
                        "ssh-agent", "-k",
                        env=subprocess_env,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await kill_proc.communicate()
                    _log.info("git_ssh_agent_stopped", ws_id=ws_id)
