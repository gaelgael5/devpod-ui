"""Dérivation des clefs d'enveloppe serveur depuis `PORTAL_VAULT_KEK`.

La primitive que `secrets/system.py` gardait pour lui, sortie ici pour ne pas
être dupliquée (fiche « Adresse de facturation au profil »). Deux propriétés :

- **sans PIN** : la clef se dérive du KEK seul, le serveur déchiffre sans que
  l'utilisateur ait déverrouillé quoi que ce soit — c'est ce qui distingue ce
  mécanisme du coffre utilisateur (`vault/crypto.derive_wrap_key`), inutilisable
  pour une donnée à relire au renouvellement ;
- **un `info` HKDF distinct PAR CONSOMMATEUR** (domain separation) : la clef des
  secrets système et celle des adresses de facturation ne sont pas la même —
  compromettre un domaine n'ouvre pas l'autre, et c'est déjà la règle du dépôt.
"""

from __future__ import annotations

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from portal.settings import get_settings


def cle_domaine(info: bytes) -> bytes:
    """Clef d'enveloppe 32 octets dérivée du KEK pour UN domaine (`info`).

    Lève si `PORTAL_VAULT_KEK` est absent : chiffrer avec une clef vide serait
    pire que refuser.
    """
    kek_hex = get_settings().portal_vault_kek
    if not kek_hex:
        raise RuntimeError("PORTAL_VAULT_KEK non configuré — impossible de dériver une clef")
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info)
    return hkdf.derive(bytes.fromhex(kek_hex))
