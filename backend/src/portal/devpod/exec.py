"""Façade d'exécution non-interactive dans un workspace (devpod ssh --stdio).

Service partagé par le router workspace_sessions et le backend MCP interne devpod
(façade I-1 : un point unique pour le saut réseau + mTLS, jamais de client SSH ad hoc).
"""

from __future__ import annotations

import asyncio
import os
import shlex
import time

import structlog

from ..config.store import load_global, safe_user_path
from .procgroup import kill_process_group, spawn_group
from .ssh_exec import control_ssh_args, devpod_ssh_key
from .ws_user import resolve_ws_user

_log = structlog.get_logger(__name__)

# rc de timeout de ws_exec — 124 (convention GNU timeout), distinct des codes
# porteurs de sens pour les sondes : 0 (ok), 1 (tmux sans serveur), 127 (commande
# absente), 255 (échec de transport SSH). Un rc=1 de timeout serait indistinguable
# d'un « aucun serveur tmux » (bug 807fed1c : injoignable confondu avec vide).
TIMEOUT_RC = 124

# rc de sonde tmux signifiant « joignable mais aucun serveur tmux » : 1 = pas de
# serveur sur le socket, 127 = tmux non installé dans le conteneur.
NO_TMUX_SERVER_RCS = (1, 127)

# Détection du socket tmux (le devcontainer peut exposer un socket non standard).
TMUX_SOCK_DETECT = (
    "TMUX_SOCK=$(find /tmp -maxdepth 2 -name default -path '*/tmux-*/*' 2>/dev/null | head -1)"
)


def tmux(args: str) -> str:
    """Préfixe une commande tmux de la détection de socket."""
    return f'{TMUX_SOCK_DETECT}; tmux ${{TMUX_SOCK:+-S "$TMUX_SOCK"}} {args}'


def remote_tmux_command(session: str) -> str:
    """Commande shell distante : session tmux persistante, fallback shell simple.

    Pour un host/VM (socket tmux par défaut de l'utilisateur SSH — pas de
    détection de socket, réservée aux devcontainers). `new-session -A` attache
    si la session existe, crée sinon. tmux absent → bash, avec un mot d'excuse.
    """
    return (
        f"command -v tmux >/dev/null 2>&1 && exec tmux new-session -A -s {shlex.quote(session)}"
        " || { echo '[portal] tmux absent : session non persistante'; exec bash -l; }"
    )


def tmux_refresh_command(sock_detect: str, tmux_prefix: str, session: str) -> str:
    """Commande shell distante : resynchronise la taille puis repeint le terminal.

    Deux temps, dans cet ordre :

    1. `kill -WINCH` sur le PID de chaque client attaché. Derrière `devpod ssh`
       (login root puis `su - <user>`), le client tmux n'a PAS de terminal de
       contrôle : le SIGWINCH émis par le TIOCSWINSZ du pont n'atteint personne,
       et le client garde sa taille d'attache pendant que xterm, lui, a changé
       (mesuré en production le 05/09 : clavier mobile ouvert, xterm à 28 lignes,
       client tmux figé à 49 — écran « décalé », que le repaint seul reproduisait
       à l'identique). Signalé directement au processus, le client relit son tty
       — que le pont a déjà mis à la bonne taille — et l'annonce au serveur
       (vérifié sur tmux 3.6, y compris sans terminal de contrôle).
    2. `refresh-client`, qui retransmet TOUT l'écran au client, comme le fait un
       `attach` (un F5) — c'est le seul moyen d'effacer les résidus déjà peints
       côté navigateur, que le redessin différentiel de tmux ne renvoie jamais
       (il croit ces cellules correctes). Un nudge de taille, lui, ne les touche
       pas.

    Le `sleep` entre les deux laisse au client le temps d'annoncer sa nouvelle
    taille au serveur : repeindre avant, c'est retransmettre l'écran à
    l'ancienne géométrie.

    On traite chaque client attaché À CETTE session (la politique « un seul
    écran » n'en laisse qu'un, mais la boucle reste correcte s'il y en avait
    plusieurs). `session` est shell-quotée ; pid et nom de client passent par
    des variables citées, jamais interpolés.
    """
    q = shlex.quote(session)
    return (
        f"{sock_detect}; "
        f"{tmux_prefix} list-clients -t {q} -F '#{{client_pid}}' 2>/dev/null | "
        'while IFS= read -r p; do kill -WINCH "$p" 2>/dev/null; done; '
        "sleep 0.2; "
        f"{tmux_prefix} list-clients -t {q} -F '#{{client_name}}' 2>/dev/null | "
        f'while IFS= read -r c; do {tmux_prefix} refresh-client -t "$c"; done'
    )


async def ws_exec(login: str, ws_id: str, command: str, timeout: float = 30.0) -> tuple[int, str]:
    """Exécute une commande non-interactive dans le devcontainer via SSH.

    ProxyCommand explicite (`devpod ssh --stdio`) : l'entrée ~/.ssh/config écrite par
    devpod est perdue au rebuild du conteneur portail. Retourne `(returncode, output)`
    où `output` fusionne stdout+stderr (les erreurs SSH partent souvent en stderr).
    """
    if ws_id.startswith("-"):
        raise ValueError(f"Insecure ws_id: {ws_id!r}")
    devpod_bin = load_global().devpod.binary
    proxy_cmd = f"{shlex.quote(devpod_bin)} ssh --stdio {shlex.quote(ws_id)}"
    env = {
        **dict(os.environ),
        "DEVPOD_HOME": str(safe_user_path(login, "devpod")),
        "HOME": os.environ.get("HOME", "/root"),
    }
    # Utilisateur du conteneur (`image_user` du profil) : celui pour lequel le
    # composant `ssh-access` a posé authorized_keys et que `AllowUsers` autorise.
    # Résolution cachée (TTL court) : ws_exec est appelé en rafale par les sondes
    # de sessions et la trentaine de primitives MCP.
    ws_user = await resolve_ws_user(login, ws_id)
    key_path = devpod_ssh_key(login)
    identity_args = ["-i", key_path, "-o", "IdentitiesOnly=yes"] if key_path else []
    # spawn_group + kill_process_group (bug 813f425f) : au timeout, tuer AUSSI le
    # ProxyCommand `devpod ssh --stdio` et sa descendance — proc.kill() seul les
    # laissait orphelins (vivants si pendus, zombies à leur mort, fuite de pids).
    proc = await spawn_group(
        "ssh",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "BatchMode=yes",
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
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        await kill_process_group(proc)
        # Libellé = contrat : create_session détecte le timeout par sous-chaîne.
        return TIMEOUT_RC, "SSH command timed out"
    output = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()
    return proc.returncode or 0, output


# Anti-empilement du pré-chauffage (incident 30/08). `_warm_running_tunnels`
# rappelle warm_tunnel à chaque rafraîchissement de l'agrégat sessions (~8 s) ;
# sans garde, un tunnel froid empilait un handshake `devpod ssh --stdio` de plus
# toutes les 8 s, chacun tué à son timeout — de la charge pure sur un nœud déjà
# saturé, et la boucle ne se refermait jamais d'elle-même.
#
# Deux gardes, par ws_id : un seul pré-chauffage EN VOL (les appels concurrents
# renoncent, ils ne font pas la queue — une file ne ferait que différer
# l'empilement), et un délai avant toute nouvelle tentative. Le délai est court
# après un succès (le master vit déjà, ControlPersist=300 s) et plus long après
# un échec : c'est le back-off qui laisse le nœud respirer.
_WARM_SUCCESS_TTL_S = 60.0
_WARM_FAILURE_COOLDOWN_S = 60.0

# ws_id -> (échéance monotonic du verdict, tunnel chaud ?)
_warm_state: dict[str, tuple[float, bool]] = {}
# ws_id dont un pré-chauffage est en cours.
_warm_inflight: set[str] = set()


def _remember_warm(ws_id: str, warm: bool) -> None:
    ttl = _WARM_SUCCESS_TTL_S if warm else _WARM_FAILURE_COOLDOWN_S
    _warm_state[ws_id] = (time.monotonic() + ttl, warm)


def reset_warm_state(ws_id: str | None = None) -> None:
    """Oublie le verdict de pré-chauffage (mutation de cycle de vie, tests).

    Ne touche PAS aux pré-chauffages en vol : leur garde protège un processus
    `ssh` réel, l'oublier autoriserait précisément le doublon qu'on évite.
    """
    if ws_id is None:
        _warm_state.clear()
    else:
        _warm_state.pop(ws_id, None)


async def warm_tunnel(login: str, ws_id: str, *, timeout: float = 20.0) -> bool:
    """Pré-chauffe le tunnel SSH d'un workspace : monte le ControlMaster en fond.

    Lance un `true` via `ws_exec` — le premier appel établit le master partagé
    (handshake mTLS via devpod), les ouvertures de terminal suivantes s'y rattachent
    instantanément. Idempotent et bon marché si déjà chaud (simple rattachement).
    Best-effort : ne lève jamais, n'émet aucun secret.

    Dédupliqué et amorti par ws_id (voir `_WARM_SUCCESS_TTL_S` /
    `_WARM_FAILURE_COOLDOWN_S`) : retourne True si le tunnel est chaud — verdict
    qui peut venir de la dernière tentative encore valide, sans nouveau handshake.
    Un appel qui renonce parce qu'un pré-chauffage est déjà en vol retourne le
    dernier verdict connu, False à défaut.
    """
    cached = _warm_state.get(ws_id)
    if cached is not None and cached[0] > time.monotonic():
        return cached[1]
    if ws_id in _warm_inflight:
        return cached[1] if cached is not None else False

    _warm_inflight.add(ws_id)
    try:
        rc, _out = await ws_exec(login, ws_id, "true", timeout=timeout)
    except Exception:
        _log.warning("ssh_warm_tunnel_failed", ws_id=ws_id, exc_info=True)
        _remember_warm(ws_id, False)
        return False
    finally:
        _warm_inflight.discard(ws_id)
    if rc != 0:
        _log.info("ssh_warm_tunnel_cold", ws_id=ws_id, rc=rc)
    _remember_warm(ws_id, rc == 0)
    return rc == 0
