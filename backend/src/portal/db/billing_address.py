"""Persistance chiffrée de l'adresse de facturation.

Deux emplacements, deux sens — et c'est le cœur de la fiche :

- **le profil** (`billing_addresses`) porte l'adresse COURANTE, celle qu'on
  modifie ;
- **l'abonnement** (`subscriptions.billing_address_enc`) porte l'adresse FIGÉE
  au moment de souscrire. Un client qui déménage ne réécrit pas l'adresse de
  ses factures passées — ce serait une falsification de pièce comptable.

Le chiffrement est celui des données serveur (KEK + HKDF, domaine dédié
`portal-billing-address`) : lisible par le portail SEUL, sans PIN — le
renouvellement et la réémission de facture n'attendent pas que l'utilisateur
déverrouille quoi que ce soit. Le blob est le JSON du modèle, chiffré entier :
aucune colonne en clair, rien d'interrogeable — et rien qui fuite dans un dump.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from ..billing.adresse import AdresseFacturation
from ..secrets.chiffrement import cle_domaine
from ..vault.crypto import decrypt_token, encrypt_token
from .tables import billing_addresses, subscriptions

#: Domaine HKDF propre aux adresses (jamais celui des secrets système).
_INFO = b"portal-billing-address"


def chiffrer_adresse(adresse: AdresseFacturation) -> bytes:
    return encrypt_token(adresse.model_dump_json(), cle_domaine(_INFO))


def dechiffrer_adresse(blob: bytes) -> AdresseFacturation:
    return AdresseFacturation.model_validate_json(decrypt_token(blob, cle_domaine(_INFO)))


async def poser_adresse(login: str, adresse: AdresseFacturation, conn: AsyncConnection) -> None:
    """Écrit l'adresse COURANTE du profil (upsert)."""
    blob = chiffrer_adresse(adresse)
    await conn.execute(
        pg_insert(billing_addresses)
        .values(login=login, adresse_enc=blob)
        .on_conflict_do_update(index_elements=["login"], set_={"adresse_enc": blob})
    )


async def lire_adresse(login: str, conn: AsyncConnection) -> AdresseFacturation | None:
    row = (
        await conn.execute(
            select(billing_addresses.c.adresse_enc).where(billing_addresses.c.login == login)
        )
    ).scalar_one_or_none()
    return None if row is None else dechiffrer_adresse(row)


async def figer_adresse(
    subscription_id: str, adresse: AdresseFacturation, conn: AsyncConnection
) -> None:
    """Fige l'adresse SUR l'abonnement : c'est celle-là qui a servi, elle ne
    bouge plus — même doctrine que l'instantané de prix."""
    await conn.execute(
        subscriptions.update()
        .where(subscriptions.c.id == subscription_id)
        .values(billing_address_enc=chiffrer_adresse(adresse))
    )


async def adresse_figee(subscription_id: str, conn: AsyncConnection) -> AdresseFacturation | None:
    row = (
        await conn.execute(
            select(subscriptions.c.billing_address_enc).where(subscriptions.c.id == subscription_id)
        )
    ).scalar_one_or_none()
    return None if row is None else dechiffrer_adresse(row)
