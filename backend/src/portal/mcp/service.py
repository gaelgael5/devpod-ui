from __future__ import annotations

import hashlib
import secrets as _secrets
import uuid

import anyio
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import mcp as db
from ..vault import session as vault_session
from ..vault.keys import get_vault_client
from .models import ApikeyCreate, BackendCreate, KeyCreate
from .runtime_secrets import encrypt_service_key

_log = structlog.get_logger(__name__)


class MCPError(Exception):
    pass


class NamespaceTaken(MCPError):
    pass


class NotFound(MCPError):
    pass


class InvalidReference(MCPError):
    pass


class VaultLocked(MCPError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


async def _require_owned_backend(
    conn: AsyncConnection, owner_login: str, backend_id: str
) -> None:
    if await db.get_backend(conn, owner_login, backend_id) is None:
        raise NotFound(f"backend '{backend_id}' introuvable")


async def create_backend(conn: AsyncConnection, owner_login: str, body: BackendCreate) -> str:
    bid = new_id()
    try:
        await db.insert_backend(
            conn,
            id=bid,
            owner_login=owner_login,
            namespace=body.namespace,
            name=body.name,
            url=body.url,
            transport=body.transport,
            auth_scheme=body.auth_scheme,
            forward_identity=body.forward_identity,
            app_url=body.app_url,
            oauth_auth_url=body.oauth_auth_url,
            quarantine_disabled=body.quarantine_disabled,
        )
    except IntegrityError as exc:
        raise NamespaceTaken(f"namespace '{body.namespace}' déjà utilisé") from exc
    _log.info("mcp_backend_created", login=owner_login, namespace=body.namespace)
    return bid


async def create_backend_key(
    conn: AsyncConnection,
    owner_login: str,
    backend_id: str,
    session_id: str,
    body: KeyCreate,
) -> str:
    await _require_owned_backend(conn, owner_login, backend_id)

    local_blob: bytes | None = None
    vault_ref: str | None = None
    vault_id: str | None = None

    if body.storage_type == "local":
        # Clé de service chiffrée avec la KEK système : la passerelle la
        # déchiffre en autonomie au runtime, sans session vault de l'owner.
        local_blob = encrypt_service_key(body.secret_value)
    else:  # harpocrate : écriture dans le coffre AVANT l'insert DB (pas de référence orpheline)
        if not body.vault_identifier:
            raise InvalidReference("vault_identifier requis pour storage_type='harpocrate'")
        if vault_session.get_master_key(session_id) is None:
            raise VaultLocked("Vault verrouillé — déverrouillez avec votre PIN")
        vault_id = body.vault_identifier
        harpo_path = f"mcp/{backend_id}/{body.slug}/value"
        vault_ref = f"${{vault://{body.vault_identifier}:{harpo_path}}}"
        harpo_client = await get_vault_client(owner_login, session_id, body.vault_identifier, conn)
        await anyio.to_thread.run_sync(
            lambda: harpo_client.secrets.create(harpo_path, body.secret_value)
        )

    kid = new_id()
    try:
        await db.insert_backend_key(
            conn,
            id=kid,
            backend_id=backend_id,
            slug=body.slug,
            description=body.description,
            storage_type=body.storage_type,
            secret_value_local=local_blob,
            secret_value_vault_ref=vault_ref,
            vault_identifier=vault_id,
        )
    except IntegrityError as exc:
        raise NamespaceTaken(f"slug '{body.slug}' déjà utilisé pour ce backend") from exc
    _log.info("mcp_backend_key_created", login=owner_login, backend_id=backend_id, slug=body.slug)
    return kid


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

APIKEY_PREFIX = "mcpk_"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_apikey(
    conn: AsyncConnection, owner_login: str, body: ApikeyCreate
) -> tuple[str, str]:
    from ..db.mcp_profiles import get_profile

    pid = body.profile_id
    if pid is not None and await get_profile(conn, owner_login, pid) is None:
        raise NotFound(f"profil '{pid}' introuvable")
    clear = APIKEY_PREFIX + _secrets.token_urlsafe(32)
    aid = new_id()
    await db.insert_apikey(
        conn,
        id=aid,
        owner_login=owner_login,
        token_hash=token_hash(clear),
        label=body.label,
        profile_id=body.profile_id,
    )
    _log.info("mcp_apikey_created", login=owner_login, apikey_id=aid)
    return aid, clear


async def rotate_apikey(
    conn: AsyncConnection, owner_login: str, apikey_id: str
) -> tuple[str, str]:
    """Rotation d'une clef manuelle : révoque l'ancienne, en émet une nouvelle.

    Même label et même profil ; l'ancien token est hors d'usage immédiatement
    (révocation, pas de grâce — la rotation est un geste de sécurité explicite).
    Réservé aux clefs bearer manuelles : les clefs workspace ont leur propre
    cycle (rotation + réinjection via agents.push.rotate_workspace_and_push) et
    les identités OAuth ne portent pas de token à roter.
    Retourne (nouvel_id, token_clair) — le clair n'est montré qu'une fois.
    """
    row = await db.get_apikey(conn, owner_login, apikey_id)
    if row is None:
        raise NotFound(f"apikey '{apikey_id}' introuvable")
    if row.get("workspace_ref"):
        raise InvalidReference(
            "clef workspace : rotation via la réinjection du workspace, pas ici"
        )
    if row.get("revoked"):
        raise InvalidReference("clef déjà révoquée — créez-en une nouvelle")
    if (row.get("kind") or "apikey") != "apikey":
        raise InvalidReference("seules les clefs bearer se rotent")
    await db.revoke_apikey(conn, owner_login, apikey_id)
    clear = APIKEY_PREFIX + _secrets.token_urlsafe(32)
    aid = new_id()
    await db.insert_apikey(
        conn,
        id=aid,
        owner_login=owner_login,
        token_hash=token_hash(clear),
        label=str(row.get("label") or ""),
        profile_id=row.get("profile_id"),
    )
    _log.info("mcp_apikey_rotated", login=owner_login, old_id=apikey_id, new_id=aid)
    return aid, clear


async def set_apikey_profile(
    conn: AsyncConnection, owner_login: str, apikey_id: str, profile_id: str | None
) -> None:
    from ..db.mcp_profiles import (
        clear_workspace_profile_override,
        get_profile,
        list_exposed_profiles,
        set_workspace_profile_override,
    )

    if profile_id is not None and await get_profile(conn, owner_login, profile_id) is None:
        raise NotFound(f"profil '{profile_id}' introuvable")
    apikey = await db.get_apikey(conn, owner_login, apikey_id)
    if apikey is None:
        raise NotFound(f"apikey '{apikey_id}' introuvable")

    ws_ref = apikey.get("workspace_ref")
    if not ws_ref:
        # Clef utilisateur classique : comportement inchangé.
        await db.set_apikey_profile(conn, owner_login, apikey_id, profile_id)
        return

    # Clef workspace : le choix de profil est PERSISTANT (survit à la rotation,
    # cf. rotate_workspace_keys). Pas de rotation ici — la clef courante est mise
    # à jour en place, l'agent en session n'est pas déconnecté.
    effective: str | None
    if profile_id is not None:
        await set_workspace_profile_override(conn, owner_login, str(ws_ref), profile_id)
        effective = profile_id
    else:
        # Retour au défaut : on efface la surcharge et la clef reprend le profil
        # exposé par défaut (0 ou 1 avec l'exposition exclusive) — pas None, sinon
        # la clef courante n'exposerait plus rien jusqu'à la prochaine rotation.
        await clear_workspace_profile_override(conn, owner_login, str(ws_ref))
        exposed = await list_exposed_profiles(conn, owner_login)
        effective = exposed[0]["id"] if exposed else None
    await db.set_apikey_profile(conn, owner_login, apikey_id, effective)
