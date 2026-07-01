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
from ..messages import db as _msg_db
from ..profiles.models import Profile
from ..recipes.models import RecipeMeta
from .env import HostNotReadyError, _find_host, build_env
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
    from ..secrets.system import reveal_system_cert

    async with _get_engine().begin() as conn:
        pem = await reveal_system_cert(slug, conn)

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

            host_port: int | None = None
            if self._exposure is not None:
                host_port = await self._exposure.allocate_port(ws_id)

            # Pour docker-tls : devcontainer.json généré localement, chemin absolu local valide.
            # Pour SSH : le fichier est généré localement puis uploadé sur la VM distante via
            #   tar|ssh avant devpod up ; le chemin absolu distant est passé à --devcontainer-path.
            dc_path: Path | None = None
            needs_devcontainer = bool(
                recipes or feature_env or ws_spec.extra_sources or profile or ws_spec.recipe_volumes
            )
            if needs_devcontainer:
                dc_path = self._write_devcontainer(
                    login,
                    ws_id,
                    recipes=recipes,
                    feature_env=feature_env,
                    extra_sources=ws_spec.extra_sources if ws_spec.extra_sources else None,
                    profile=profile,
                    recipe_volumes=ws_spec.recipe_volumes or None,
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

            # Le tunnel openvscode (ssh -o ProxyCommand "devpod ssh --stdio") est
            # bindé sur 0.0.0.0:{host_port} DANS le conteneur portail pour tous les
            # types de host : l'upstream des routes Caddy / URLs est donc toujours
            # le portail, jamais le nœud (dont le pare-feu n'expose que 2376).
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
                    ssh_key_path=tmp_key_path,
                    request_host=request_host,
                    workspace_folder=workspace_folder,
                    host_name=host_cfg.name,
                    git_ssh_key_path=git_ssh_key_path,
                )
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            task_created = True
            _log.info("workspace_up_started", ws_id=ws_id, login=login)
            return ws_id
        finally:
            if not task_created and tmp_key_path and tmp_key_path.startswith(tempfile.gettempdir()):
                with contextlib.suppress(OSError):
                    os.unlink(tmp_key_path)

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
        """
        try:
            user_cfg = await load_user(login)
            ws_name = ws_id.removeprefix(f"{login}-")
            ws_spec = next((w for w in user_cfg.workspaces if w.name == ws_name), None)
            if ws_spec is None:
                _log.warning("reconcile_ws_spec_not_found", ws_id=ws_id, login=login)
                return
            _log.info("reconcile_triggering_devpod_up", ws_id=ws_id, login=login)
            await self.up(login, ws_spec)
        except Exception as exc:
            _log.warning("reconcile_reconnect_failed", ws_id=ws_id, error=str(exc))

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
                asyncio.create_task(self._reconnect_workspace(ws_id, login_for_key))
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
                tunnel_env["DOCKER_CERT_PATH"] = global_cfg.devpod.client_cert_path
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
        tunnel) en arrière-plan et rend la main immédiatement.
        """
        asyncio.create_task(self._reconnect_workspace(ws_id, login))  # noqa: RUF006

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
        await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id, timeout_s=120)
        async with _get_engine().begin() as _conn:
            await persist_log_blob_from_file(ws_id, login, "stop", log_path, _conn)
        await self._write_status(ws_id, "stopped", login=login)
        _log.info("workspace_stopped", ws_id=ws_id, login=login)

    async def delete(self, login: str, ws_id: str, *, shelve: bool = True) -> dict[str, Any]:
        """Supprime un workspace (force). Shelve le travail en attente si shelve=True."""
        # Tuer le subprocess en cours (ex. devpod up en provisioning) pour libérer le verrou
        # avant d'appeler shelve ou run_subprocess(delete).
        await kill_if_running(ws_id)
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
        rc = await run_subprocess(cmd=cmd, env=env, log_path=log_path, ws_id=ws_id, timeout_s=120)
        if rc != 0:
            _log.warning("workspace_delete_failed", ws_id=ws_id, returncode=rc)
        ws_name = ws_id.removeprefix(f"{login}-")
        async with _get_engine().begin() as conn:
            await persist_log_blob_from_file(ws_id, login, "delete", log_path, conn)
            await delete_status_db(ws_id, conn)
            await _msg_db.purge_workspace_messages(conn, login, ws_name)
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
        recipes: list[RecipeMeta] | None = None,
        feature_env: dict[str, str] | None = None,
        extra_sources: list[SourceSpec] | None = None,
        profile: Profile | None = None,
        recipe_volumes: list[str] | None = None,
    ) -> Path:
        """Écrit devcontainer.json + Feature dirs dans un tmpdir. Retourne le chemin du JSON."""
        user_dir = safe_user_path(login, "devpod")
        user_dir.mkdir(parents=True, exist_ok=True)

        tmp_dir = Path(tempfile.mkdtemp(dir=user_dir, prefix=f"{ws_id}-dc-"))
        try:
            content: dict[str, Any] = {
                "image": "mcr.microsoft.com/devcontainers/base:ubuntu",
            }

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
                        dep_ids = [
                            key_to_id[k]
                            for k in recipe.installs_after
                            if k in key_to_id
                        ]
                        if dep_ids:
                            fd: dict[str, Any] = json.loads(
                                feature_json.read_text(encoding="utf-8")
                            )
                            fd["installsAfter"] = [f"./{d}" for d in dep_ids]
                            feature_json.write_text(
                                json.dumps(fd, indent=2), encoding="utf-8"
                            )
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

            if recipe_volumes and recipes:
                mounts: list[str] = []
                for recipe in recipes:
                    if recipe.memory_volume is not None and recipe.id in recipe_volumes:
                        vol_name = f"{ws_id}-{recipe.memory_volume.name}"
                        mounts.append(
                            f"source={vol_name},"
                            f"target={recipe.memory_volume.mapping.target},"
                            f"type=volume"
                        )
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
            "-i", ssh_key_path,
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15",
        ]
        ssh_target = f"{ssh_user}@{ssh_host}"

        # Récupérer le home dir réel de l'utilisateur SSH
        home_proc = await asyncio.create_subprocess_exec(
            "ssh", *ssh_opts, ssh_target, "echo $HOME",
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
        devpod_workspaces = (
            f"{home}/.devpod/agent/contexts/default/workspaces"
        )
        remote_dir = f"{devpod_workspaces}/.devpod-portal-dc/{ws_id}"
        devcontainer_path = f"../../.devpod-portal-dc/{ws_id}/devcontainer.json"

        remote_cmd = (
            f"mkdir -p {shlex.quote(remote_dir)} && "
            f"tar xzf - -C {shlex.quote(remote_dir)}"
        )

        tar_proc = await asyncio.create_subprocess_exec(
            "tar", "czf", "-", "-C", str(dc_dir), ".",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        ssh_proc = await asyncio.create_subprocess_exec(
            "ssh", *ssh_opts, ssh_target, remote_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _pump() -> None:
            assert tar_proc.stdout is not None
            assert ssh_proc.stdin is not None
            try:
                while chunk := await tar_proc.stdout.read(65536):
                    ssh_proc.stdin.write(chunk)
                await ssh_proc.stdin.drain()
            finally:
                ssh_proc.stdin.close()

        pump_task = asyncio.create_task(_pump())
        _, ssh_err = await ssh_proc.communicate()
        await pump_task
        await tar_proc.wait()

        if tar_proc.returncode != 0:
            raise RuntimeError(f"tar devcontainer échoué (code {tar_proc.returncode})")
        if ssh_proc.returncode != 0:
            raise RuntimeError(
                f"Upload SSH devcontainer vers {remote_dir!r} échoué : "
                f"{ssh_err.decode(errors='replace').strip()}"
            )
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
            "-i", ssh_key_path,
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
        ]
        proc = await asyncio.create_subprocess_exec(
            "ssh", *ssh_opts, f"{ssh_user}@{ssh_host}",
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
        proxy_cmd = f"{shlex.join(self._devpod_bin)} ssh --stdio {shlex.quote(ws_id)}"
        cmd = [
            "ssh",
            "-N",
            "-o", f"ProxyCommand={proxy_cmd}",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-L", f"0.0.0.0:{host_port}:localhost:{_OPENVSCODE_SERVER_PORT}",
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
            if remote_dc_dir and ssh_host and ssh_key_path:
                with contextlib.suppress(Exception):
                    await self._cleanup_ssh_dir(remote_dc_dir, ssh_user, ssh_host, ssh_key_path)
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
            if ssh_key_path and ssh_key_path.startswith(tempfile.gettempdir()):
                with contextlib.suppress(OSError):
                    os.unlink(ssh_key_path)
