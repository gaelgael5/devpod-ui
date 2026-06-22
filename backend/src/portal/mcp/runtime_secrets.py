from __future__ import annotations

from typing import cast

import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .. import settings as _settings_module
from ..secrets.resolver import EnvSecretResolver, SecretAccessError
from ..secrets.types import Secret
from ..vault.crypto import decrypt_token, encrypt_token

log = structlog.get_logger(__name__)


class KekUnavailable(Exception):
    """PORTAL_VAULT_KEK absent : impossible de chiffrer/déchiffrer une clé de service."""


class UnresolvableSecret(Exception):
    """Clé non résoluble au runtime (ex. référence vault/wallet dépendante d'une session)."""


def _derive_kek() -> bytes:
    kek_hex = _settings_module.get_settings().portal_vault_kek
    if not kek_hex:
        log.warning("mcp_kek_unavailable")
        raise KekUnavailable("PORTAL_VAULT_KEK non configuré")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"mcp-backend-key-v1",
    )
    return hkdf.derive(bytes.fromhex(kek_hex))


def encrypt_service_key(plaintext: str) -> bytes:
    return encrypt_token(plaintext, _derive_kek())


def decrypt_service_key(blob: bytes) -> str:
    return decrypt_token(blob, _derive_kek())


_env_resolver = EnvSecretResolver()


async def resolve_grant_key(key_row: dict[str, object] | None) -> Secret | None:
    """Résout la clé de service d'un grant en bearer clair.

    `key_row` doit contenir les clés `storage_type`, `secret_value_local`,
    `secret_value_vault_ref` (utiliser un fetcher runtime dédié qui sélectionne
    le blob chiffré — pas `get_backend_key`/`list_backend_keys`, qui l'omettent
    par hygiène). `None` = backend public (aucune clé). Lève UnresolvableSecret
    pour une référence vault (harpocrate) non résoluble sans session, ou un
    storage_type inconnu.
    """
    if key_row is None:
        return None
    storage = key_row["storage_type"]
    if storage == "local":
        blob = key_row["secret_value_local"]
        if blob is None:
            raise UnresolvableSecret("clé 'local' sans valeur chiffrée")
        return Secret(decrypt_service_key(cast(bytes, blob)))
    if storage != "harpocrate":
        raise UnresolvableSecret(f"storage_type inconnu : {storage!r}")
    # harpocrate : seule une référence ${env://...} est résoluble au runtime
    ref = cast(str, key_row.get("secret_value_vault_ref") or "")
    if ref.startswith("${env://"):
        try:
            return await _env_resolver.resolve(ref)
        except SecretAccessError as exc:
            raise UnresolvableSecret(str(exc)) from exc
    raise UnresolvableSecret("référence vault non résoluble au runtime (harpocrate différé)")
