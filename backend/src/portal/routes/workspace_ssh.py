from __future__ import annotations

import asyncio
import base64
import re
import shlex
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, WebSocket

from ..auth.rbac import UsernameError, session_within_max_age
from ..config.store import load_global
from ..db.engine import _get_engine
from ..db.recipes import load_recipes_as_dict
from ..db.test_hosts import list_test_hosts_for_workspace
from ..devpod.ssh_exec import control_ssh_args
from ..devpod.ssh_exec import devpod_ssh_key as _devpod_ssh_key
from ..devpod.test_vm import build_testhost_ssh_command
from ..sessions import registry
from ..sessions.ownership import OwnershipDenied, resolve_owner
from ..sessions.pty_bridge import requested_size, run_pty_bridge
from ..settings import get_settings

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["workspace-ssh"])

_WS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_SESSION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}$")


@router.websocket("/workspaces/{name}/ssh")
async def workspace_ssh_terminal(
    name: str,
    websocket: WebSocket,
    session: str | None = None,
    start: str | None = None,
    shell: bool = False,
    ssh_test: str | None = None,
    owner: str | None = None,
    cols: int | None = None,
    rows: int | None = None,
) -> None:
    await websocket.accept()
    settings = get_settings()
    cfg = load_global()

    # ── Origin validation (anti-CSWSH) ────────────────────────────────────────
    if not settings.dev_mode:
        parsed = urlparse(cfg.server.external_url)
        allowed_origin = f"{parsed.scheme}://{parsed.netloc}"
        request_origin = websocket.headers.get("origin", "").rstrip("/")
        if request_origin != allowed_origin:
            _log.warning(
                "ws_workspace_ssh_bad_origin",
                origin=request_origin,
                allowed=allowed_origin,
            )
            await websocket.close(code=4003, reason="Bad origin")
            return

    # ── Auth ──────────────────────────────────────────────────────────────────
    user_data = websocket.session.get("user")
    if not user_data or not isinstance(user_data, dict):
        _log.warning(
            "ws_workspace_ssh_unauthenticated",
            workspace=name,
            session_is_empty=not bool(websocket.session),
            session_keys=list(websocket.session.keys()),
        )
        await websocket.close(code=4001, reason="Not authenticated")
        return
    if not session_within_max_age(websocket.session):
        # Plafond d'âge absolu (bug 032) : session expirée → re-login requis.
        await websocket.close(code=4001, reason="Session expired")
        return
    login: str = user_data.get("login", "")
    if not login:
        await websocket.close(code=4001, reason="Invalid session")
        return

    # ── Owner effectif (admin peut cibler le conteneur d'un autre user) ───────
    roles = user_data.get("roles", [])
    try:
        effective_owner = resolve_owner(
            login=login, roles=roles if isinstance(roles, list) else [], owner=owner
        )
    except OwnershipDenied:
        _log.warning("ws_workspace_ssh_owner_denied", login=login, owner=owner)
        await websocket.close(code=4001, reason="Admin role required")
        return
    except UsernameError:
        await websocket.close(code=4022, reason="Invalid owner")
        return

    # ── Validation du nom de workspace ────────────────────────────────────────
    if not _WS_NAME_RE.fullmatch(name):
        await websocket.close(code=4022, reason="Invalid workspace name")
        return

    ws_id = f"{effective_owner}-{name}"

    # ── Résolution de la commande tmux ───────────────────────────────────────
    # Le serveur tmux tourne en uid 1000 (vscode) ; root peut accéder à son
    # socket Unix car root bypasse les DAC.  On détecte le socket actif dans
    # /tmp/tmux-*/ et on passe -S $SOCK à tmux — pas besoin de su.
    _sock = (
        "TMUX_SOCK=$(find /tmp -maxdepth 2 -name default -path '*/tmux-*/*' 2>/dev/null | head -1)"
    )
    _tmux = 'TERM=xterm-256color tmux ${TMUX_SOCK:+-S "$TMUX_SOCK"}'

    # Sortie du copy-mode AVANT toute attache. Le défilement tactile mobile
    # navigue l'historique via copy-mode ; une déconnexion à ce moment-là LAISSE
    # la session en copy-mode, et tout client qui se rattache voit l'instantané
    # figé de cet instant, la saisie absorbée sans écho — une session qui
    # paraît morte alors qu'elle vit (mesuré en production le 05/09 :
    # `pane_in_mode=1`, seul `send-keys -X cancel` la rendait). L'échec est
    # silencieux quand il n'y a ni session ni mode : c'est le cas nominal.
    def _sortie_copy_mode(session_cible: str) -> str:
        return f"{_tmux} send-keys -t {shlex.quote(session_cible)} -X cancel 2>/dev/null"

    tmux_cmd: str
    # Nom de session tmux attaché (pour le registre des terminaux vivants) : None
    # quand aucun tmux n'est en jeu (rebond test, shell brut).
    session_name: str | None = None
    term_family: registry.Family = "workspace"
    term_target = ws_id
    if ssh_test is not None:
        # Rebond vers une machine de test : depuis le container, `ssh root@<ip>` par la
        # clé du container. L'IP est résolue côté serveur ; accès refusé si le host
        # n'appartient pas aux test-hosts de ce workspace.
        async with _get_engine().connect() as _conn:
            allowed = await list_test_hosts_for_workspace(effective_owner, name, _conn)
        testhost_cmd = build_testhost_ssh_command(ssh_test, allowed, cfg.hosts)
        if testhost_cmd is None:
            await websocket.close(code=4022, reason="Test host not available")
            return
        tmux_cmd = testhost_cmd
        term_family = "test"
        term_target = ssh_test
        # Le rebond ouvre une session tmux persistante sur la VM (cf. test_vm).
        session_name = "main"
    elif shell:
        # Mode shell brut : bash interactif sans tmux — utile pour le debug.
        tmux_cmd = "exec bash -l"
    elif session is not None:
        if not _SESSION_NAME_RE.fullmatch(session):
            await websocket.close(code=4022, reason="Invalid session name")
            return
        # new-session -A : attache si la session existe, crée sinon.
        tmux_cmd = (
            f"{_sock}; {_sortie_copy_mode(session)}; "
            f"{_tmux} new-session -A -s {shlex.quote(session)}"
        )
        session_name = session
    elif start is not None:
        from ..recipes.models import _RECIPE_ID_RE

        if not _RECIPE_ID_RE.fullmatch(start):
            await websocket.close(code=4022, reason=f"Invalid start recipe id {start!r}")
            return

        async with _get_engine().connect() as _conn:
            available = await load_recipes_as_dict(effective_owner, _conn, type_filter="start")
        if start not in available:
            await websocket.close(code=4022, reason=f"Start recipe {start!r} not found")
            return

        # Fallback bundlé inclus (start validé par _RECIPE_ID_RE → pas de traversal).
        from .workspace_sessions import locate_start_sh

        start_sh_path = locate_start_sh(effective_owner, start)
        if start_sh_path is None:
            await websocket.close(code=4022, reason=f"start.sh missing for {start!r}")
            return

        script_content = start_sh_path.read_text(encoding="utf-8")
        b64 = base64.b64encode(script_content.encode()).decode()
        run_script = f'bash -lc "$(echo {b64} | base64 -d)"'
        has_tmux = "command -v tmux >/dev/null 2>&1"
        tmux_cmd = (
            f"{has_tmux} && {_sock}; {_sortie_copy_mode(start)}; "
            f"{_tmux} new -A -s {start} -- {run_script} || {run_script}"
        )
        session_name = start
    else:
        tmux_cmd = f"{_sock}; {_sortie_copy_mode('main')}; {_tmux} new -A -s main || bash -l"
        session_name = "main"

    # ── Build commande SSH ────────────────────────────────────────────────────
    # ProxyCommand explicite : n'utilise plus ~/.ssh/config (perdu au rebuild).
    # -t -t force l'allocation PTY même quand stdin est un pipe.
    if ws_id.startswith("-"):
        await websocket.close(code=4022, reason="Invalid workspace SSH host")
        return
    devpod_bin = cfg.devpod.binary
    proxy_cmd = f"{shlex.quote(devpod_bin)} ssh --stdio {shlex.quote(ws_id)}"
    key_path = _devpod_ssh_key(effective_owner)
    identity_args = ["-i", key_path, "-o", "IdentitiesOnly=yes"] if key_path else []
    # Utilisateur du conteneur (`image_user` du profil) — le terminal doit ouvrir
    # la session sous le MÊME compte que celui qui possède le socket tmux et
    # l'`authorized_keys` posés par le composant `ssh-access`.
    from ..devpod.ws_user import resolve_ws_user

    ws_user = await resolve_ws_user(effective_owner, ws_id)
    cmd = [
        "ssh",
        "-t",
        "-t",
        *identity_args,
        *control_ssh_args(ws_id, ws_user),
        "-o",
        f"ProxyCommand={proxy_cmd}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "--",
        f"{ws_user}@devpod-ws",
        tmux_cmd,
    ]

    # Env complet (DEVPOD_HOME + DOCKER_* pour docker-tls) → devpod ssh --stdio
    # trouve la config workspace ET peut joindre le daemon du nœud.
    from ..devpod.ssh_exec import workspace_env

    devpod_env = {
        **(await workspace_env(effective_owner, ws_id)),
        # SSH propage TERM local vers le PTY remote avec -t -t.
        # Le processus portal n'a pas de vrai terminal → forcer xterm-256color.
        "TERM": "xterm-256color",
    }

    _log.info(
        "ws_workspace_ssh_open",
        ws_id=ws_id,
        actor=login,
        owner=effective_owner,
        cross_user=effective_owner != login,
        start=start,
        ssh_test=ssh_test,
    )

    # Enregistrement du terminal vivant (vue centralisée des sessions) ; le pont
    # PTY (resize, stdin, teardown) est mutualisé dans sessions/pty_bridge.
    live_term = registry.new_terminal(
        family=term_family, target=term_target, owner=effective_owner, session=session_name
    )
    # Repaint plein écran (bouton « Rafraîchir ») : `tmux refresh-client`
    # retransmet TOUT l'écran au client, seul moyen d'effacer les résidus déjà
    # peints côté navigateur (le redessin différentiel de tmux ne les renvoie
    # jamais). On rejoue la MÊME commande ssh que le terminal, sans `-t -t` et
    # avec la commande de rafraîchissement : même transport, même user, même
    # socket, donc accès garanti. Seulement pour un vrai terminal tmux de
    # session (pas shell brut, pas rebond VM dont le socket diffère).
    from collections.abc import Awaitable, Callable

    from ..devpod.exec import tmux_refresh_command

    # Toute session tmux LOCALE au conteneur (session explicite, recette `start`,
    # ou `main` par défaut), qui partage la détection de socket `_sock`. Exclu :
    # le rebond VM (`ssh_test`), dont le socket tmux est celui, différent, de
    # l'utilisateur SSH distant ; et le shell brut (session_name None).
    on_redraw: Callable[[], Awaitable[None]] | None = None
    if session_name is not None and ssh_test is None:
        refresh_remote = tmux_refresh_command(_sock, _tmux, session_name)
        # Sans `-t` : le rafraîchissement est une commande courte non
        # interactive, pas besoin d'allouer un PTY (le terminal, lui, en a un).
        redraw_cmd = [arg for arg in cmd if arg != "-t"]
        redraw_cmd[-1] = refresh_remote

        async def _do_redraw() -> None:
            proc = await asyncio.create_subprocess_exec(
                *redraw_cmd,
                env=devpod_env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
            if proc.returncode != 0:
                _log.warning(
                    "ws_workspace_ssh_redraw_failed",
                    rc=proc.returncode,
                    err=err.decode(errors="replace")[:200],
                )

        on_redraw = _do_redraw

    returncode = await run_pty_bridge(
        websocket,
        cmd,
        devpod_env,
        live_term,
        log_label="ws_workspace_ssh",
        initial_size=requested_size(cols, rows),
        on_redraw=on_redraw,
    )

    _log.info("ws_workspace_ssh_closed", ws_id=ws_id, returncode=returncode)
