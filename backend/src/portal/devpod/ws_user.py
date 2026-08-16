"""Utilisateur SSH d'un workspace (`image_user` du profil) — source de vérité unique.

Le portail PROVISIONNE pour cet utilisateur : le composant `ssh-access` pose
`authorized_keys` dans son foyer et restreint `AllowUsers` à lui, et le host
Termix se connecte sous son nom. Les façades d'exécution (`ws_exec`,
`build_ssh_argv`, terminal interactif) doivent donc viser le MÊME utilisateur —
elles codaient `vscode` en dur, ce qui cassait tout le post-readiness dès qu'un
profil définissait un autre `image_user`.

La résolution lit le profil en base : elle est mise en cache (TTL court) car
`ws_exec` est appelé en rafale par les sondes de sessions (TTL 4 s) et par la
trentaine de primitives MCP — une lecture par appel serait une régression de
perf. Le cache s'auto-guérit au TTL ; `invalidate` permet de le vider tout de
suite après un changement de profil.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Literal, cast

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_log = structlog.get_logger(__name__)

# Utilisateur de l'image de base devcontainer — repli quand aucun profil ne
# définit d'`image_user`, et en cas d'erreur de résolution (fail-safe : c'est le
# comportement historique, jamais pire que l'ancien codage en dur).
DEFAULT_WS_USER = "vscode"

_CACHE_TTL_S = 60.0
_cache: dict[str, tuple[float, str]] = {}


def _ws_name(login: str, ws_id: str) -> str:
    """Nom court du workspace (ws_id = `<login>-<name>`) ; ws_id tel quel sinon."""
    return ws_id[len(login) + 1 :] if ws_id.startswith(f"{login}-") else ws_id


async def resolve_ws_user_db(login: str, ws_id: str, conn: AsyncConnection | Any) -> str:
    """Utilisateur SSH du workspace, lu en base sur la connexion fournie (sans cache)."""
    # Imports différés : ce module est importé par les façades SSH (ssh_exec,
    # exec), qui doivent rester légères — le dépôt de profils tire yaml & co.
    from ..db.profiles import AsyncProfileRepository
    from ..db.user_config import get_workspace_profile_ref_db
    from ..profiles.repository import ProfileError

    ref = await get_workspace_profile_ref_db(login, _ws_name(login, ws_id), conn)
    if ref is None or ref[0] not in ("shared", "user"):
        return DEFAULT_WS_USER
    try:
        profile = await AsyncProfileRepository().get(
            cast("Literal['shared', 'user']", ref[0]), ref[1], login
        )
    except ProfileError:
        return DEFAULT_WS_USER
    return profile.image_user or DEFAULT_WS_USER


async def resolve_ws_user(login: str, ws_id: str) -> str:
    """Utilisateur SSH du workspace, caché (TTL court). Ouvre sa propre connexion.

    Ne lève jamais : toute erreur retombe sur `DEFAULT_WS_USER`, pour qu'une base
    indisponible ne casse pas une exécution qui, avant, marchait en dur.
    """
    hit = _cache.get(ws_id)
    now = time.monotonic()
    if hit is not None and hit[0] > now:
        return hit[1]
    try:
        from ..db.engine import _get_engine

        async with _get_engine().connect() as conn:
            user = await resolve_ws_user_db(login, ws_id, conn)
    except Exception:
        _log.warning("resolve_ws_user_failed", ws_id=ws_id, exc_info=True)
        return DEFAULT_WS_USER
    _cache[ws_id] = (now + _CACHE_TTL_S, user)
    return user


def invalidate(ws_id: str) -> None:
    """Oublie l'utilisateur caché d'un workspace (changement de profil, `up`)."""
    _cache.pop(ws_id, None)


def clear_cache() -> None:
    """Vide le cache. Usage tests uniquement."""
    _cache.clear()
