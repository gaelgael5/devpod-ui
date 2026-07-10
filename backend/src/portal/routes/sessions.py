"""Vue centralisée des sessions actives — `GET /sessions`.

Agrège les terminaux (conteneurs tmux, hosts admin, VM de test) accessibles à
l'appelant. La création/fermeture N'EST PAS dupliquée ici : le frontend réutilise
les endpoints existants `POST/DELETE /me/workspaces/{name}/sessions`.

TODO(sessions): la fermeture d'un terminal host/VM de test n'a pas d'endpoint
dédié aujourd'hui (le terminal se ferme en coupant le websocket) ; ne pas
l'inventer ici tant que le besoin produit n'est pas cadré.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..auth.rbac import UserInfo, require_user
from ..sessions.aggregate import list_sessions
from ..settings import get_settings

router = APIRouter(tags=["sessions"])


def _is_admin(user: UserInfo) -> bool:
    """Admin = rôle admin OIDC présent dans les rôles de session (comme ssh_proxy)."""
    return get_settings().oidc_admin_role in user.roles


@router.get("/sessions")
async def get_sessions(user: UserInfo = Depends(require_user)) -> list[dict[str, Any]]:
    return await list_sessions(login=user.login, is_admin=_is_admin(user))
