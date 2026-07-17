"""Cycle de vie des clefs API par workspace × profil exposé (spec 35).

Une clef workspace est une mcp_apikey portant workspace_ref = ws_id. Elle est
régénérée à chaque `up` (rotation systématique), révoquée à la suppression du
workspace et au décochage « exposé aux workspaces » du profil (fail closed).

Les tokens clairs retournés ne servent qu'au rendu des fichiers de configuration
des agents — ils ne sont jamais loggés ni persistés en clair.
"""

from __future__ import annotations

import secrets as _secrets
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import mcp as db
from ..db.mcp_profiles import list_exposed_profiles
from ..mcp.service import APIKEY_PREFIX, new_id, token_hash

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class WorkspaceKey:
    apikey_id: str
    profile_id: str
    profile_name: str
    token: str  # clair, réservé au rendu — jamais loggé


async def rotate_workspace_keys(
    conn: AsyncConnection, owner_login: str, ws_id: str
) -> list[WorkspaceKey]:
    """Révoque la génération précédente et crée une clef par profil exposé."""
    revoked = await db.revoke_workspace_apikeys(conn, owner_login, ws_id)
    keys: list[WorkspaceKey] = []
    for profile in await list_exposed_profiles(conn, owner_login):
        clear = APIKEY_PREFIX + _secrets.token_urlsafe(32)
        aid = new_id()
        await db.insert_apikey(
            conn,
            id=aid,
            owner_login=owner_login,
            token_hash=token_hash(clear),
            label=f"ws:{ws_id}/{profile['name']}",
            profile_id=profile["id"],
            workspace_ref=ws_id,
        )
        keys.append(
            WorkspaceKey(
                apikey_id=aid,
                profile_id=profile["id"],
                profile_name=profile["name"],
                token=clear,
            )
        )
    _log.info(
        "workspace_keys_rotated",
        login=owner_login,
        ws_id=ws_id,
        revoked=revoked,
        created=len(keys),
    )
    return keys


async def revoke_workspace_keys(conn: AsyncConnection, owner_login: str, ws_id: str) -> int:
    """Révoque toutes les clefs du workspace (suppression du workspace)."""
    from ..db.agent_sync import delete_config_hash

    n = await db.revoke_workspace_apikeys(conn, owner_login, ws_id)
    # Oublie l'empreinte : un ws_id réutilisé doit re-livrer (pas de skip fantôme).
    await delete_config_hash(conn, ws_id)
    _log.info("workspace_keys_revoked", login=owner_login, ws_id=ws_id, revoked=n)
    return n


async def revoke_profile_workspace_keys(
    conn: AsyncConnection, owner_login: str, profile_id: str
) -> list[str]:
    """Fail closed au décochage du profil : révoque ses clefs workspace.

    Retourne les ws_id affectés, à repasser au générateur de fichiers pour
    retirer l'entrée du profil sur les hosts.
    """
    affected = await db.revoke_profile_workspace_apikeys(conn, owner_login, profile_id)
    _log.info(
        "profile_workspace_keys_revoked",
        login=owner_login,
        profile_id=profile_id,
        workspaces=affected,
    )
    return affected
