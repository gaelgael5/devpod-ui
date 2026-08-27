"""Propriété d'une machine dédiée, invités, et quota de workspaces.

Deux plafonds distincts s'appliquent à une machine, et leur ordre n'est pas
négociable :

1. **La capacité de la machine prime sur tout.** Ce n'est pas une règle
   commerciale mais une limite PHYSIQUE : c'est le nombre de workspaces que la
   machine peut faire tourner sans planter. Aucun forfait, aussi généreux
   soit-il, ne la fait dépasser — on n'achète pas de la RAM avec un abonnement.
2. **Le quota du forfait** vient ensuite. Il peut être plus bas que la capacité
   (on n'a payé que pour trois places sur une machine qui en tient dix) ; il ne
   peut jamais la relever.

C'est une capacité de MACHINE, pas un quota individuel : elle est partagée entre
le propriétaire et les invités qu'il a conviés. Un invité peut recevoir une
sous-limite ; le propriétaire, lui, consomme ce qui reste.

Ce module ne fait que décider. Il ne lit pas la base : l'appelant lui fournit
l'état, il rend un verdict motivé — ce qui le rend testable sans base et donne
un message d'erreur exploitable côté UI.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Validation d'adresse volontairement permissive : on refuse ce qui n'est
# manifestement pas une adresse, on ne prétend pas valider le RFC 5322.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

HostingType = Literal["dedie", "mutualise"]
GuestState = Literal["invite", "accepte", "revoque"]


class QuotaDepasse(Exception):
    """La création de workspace est refusée (FR, message affichable)."""


class HostOwnership(BaseModel):
    """Rattachement d'une machine à son propriétaire, et ses deux plafonds.

    `capacity_workspaces` est ce que la machine SUPPORTE : le nombre de
    workspaces qui peuvent y tourner sans la faire planter. C'est une donnée de
    dimensionnement, pas une donnée commerciale, et elle prime sur tout.

    `offer_max_workspaces` est le quota du forfait qui a provisionné la machine,
    figé au provisionnement — un changement de catalogue ne redimensionne pas
    rétroactivement une machine déjà livrée.

    `None` = pas de plafond de ce côté-là.
    """

    model_config = ConfigDict(extra="forbid")

    host_name: str
    owner_login: str
    hosting_type: HostingType = "dedie"
    offer_slug: str | None = None
    capacity_workspaces: int | None = Field(default=None, ge=0)
    offer_max_workspaces: int | None = Field(default=None, ge=0)


class HostGuest(BaseModel):
    """Invité d'une machine dédiée.

    On invite une ADRESSE, pas un compte : `login` reste `None` tant que
    l'invitation n'est pas acceptée. C'est ce qui permet d'inviter quelqu'un qui
    n'a pas encore de compte sur le portail.
    """

    model_config = ConfigDict(extra="forbid")

    host_name: str
    email: str
    login: str | None = None
    allocated_workspaces: int | None = Field(default=None, gt=0)
    state: GuestState = "invite"
    token: str = ""
    expires_at: datetime | None = None

    @field_validator("email")
    @classmethod
    def _adresse(cls, v: str) -> str:
        if not _EMAIL_RE.match(v.strip()):
            raise ValueError(f"adresse email invalide : {v!r}")
        return v.strip().lower()

    @property
    def actif(self) -> bool:
        return self.state == "accepte" and bool(self.login)


def nouveau_token() -> str:
    """Jeton d'invitation, usage unique.

    `token_urlsafe(32)` = 256 bits d'entropie : le lien circule par email, il
    doit être indevinable même si l'adresse du destinataire est connue.
    """
    return secrets.token_urlsafe(32)


def invitation_valide(guest: HostGuest, maintenant: datetime) -> bool:
    """Une invitation encore acceptable : ni acceptée, ni révoquée, ni expirée."""
    if guest.state != "invite":
        return False
    if guest.expires_at is None:
        return True
    return guest.expires_at > maintenant


def limite_effective(ownership: HostOwnership) -> tuple[int | None, str]:
    """Plafond réellement opposable, et sa nature : `machine`, `forfait` ou `""`.

    La nature n'est pas cosmétique : elle décide de ce qu'on dit à l'utilisateur
    quand il est bloqué. « Capacité de la machine atteinte » appelle une machine
    plus grosse, « quota du forfait atteint » appelle un forfait supérieur. Les
    confondre, c'est envoyer l'utilisateur payer pour rien.

    À égalité, c'est la machine qui est nommée : c'est la contrainte dure.
    """
    capacite = ownership.capacity_workspaces
    quota = ownership.offer_max_workspaces

    if capacite is None and quota is None:
        return None, ""
    if quota is None:
        return capacite, "machine"
    if capacite is None:
        return quota, "forfait"
    return (capacite, "machine") if capacite <= quota else (quota, "forfait")


def capacite_restante(ownership: HostOwnership, utilises: int) -> int | None:
    """Places libres sur la machine, `None` si aucun plafond ne s'applique."""
    limite, _ = limite_effective(ownership)
    if limite is None:
        return None
    return max(0, limite - utilises)


def logins_autorises(ownership: HostOwnership, guests: list[HostGuest]) -> set[str]:
    """Comptes ayant le droit de poser un workspace sur cette machine."""
    return {ownership.owner_login} | {g.login for g in guests if g.actif and g.login}


def verifier_creation(
    ownership: HostOwnership,
    guests: list[HostGuest],
    utilisation: dict[str, int],
    login: str,
) -> None:
    """Vérifie qu'un compte peut créer un workspace de plus sur cette machine.

    `utilisation` = nombre de workspaces déjà posés sur CETTE machine, par
    login. Lève `QuotaDepasse` avec un message affichable, ou ne fait rien.

    Les trois refus, dans l'ordre où ils comptent :

    1. le compte n'est ni propriétaire ni invité accepté ;
    2. le plafond de la machine est atteint — capacité physique d'abord, quota
       du forfait ensuite ; il prime sur toute allocation individuelle ;
    3. l'invité a une sous-limite et l'a atteinte.

    Le message de refus distingue la capacité machine du quota de forfait :
    l'un appelle une machine plus grosse, l'autre un forfait supérieur.
    """
    if login not in logins_autorises(ownership, guests):
        raise QuotaDepasse(
            f"{login} n'est ni propriétaire ni invité de la machine {ownership.host_name}"
        )

    total = sum(utilisation.values())
    limite, nature = limite_effective(ownership)
    if limite is not None and total >= limite:
        if nature == "machine":
            raise QuotaDepasse(
                f"capacité de la machine {ownership.host_name} atteinte "
                f"({total}/{limite} workspaces) : elle ne peut pas en faire "
                "tourner davantage sans planter"
            )
        raise QuotaDepasse(
            f"quota du forfait atteint sur {ownership.host_name} ({total}/{limite} workspaces)"
        )

    invite = next((g for g in guests if g.actif and g.login == login), None)
    if invite is not None and invite.allocated_workspaces is not None:
        consommes = utilisation.get(login, 0)
        if consommes >= invite.allocated_workspaces:
            raise QuotaDepasse(
                f"allocation de {login} atteinte sur {ownership.host_name} "
                f"({consommes}/{invite.allocated_workspaces} workspaces)"
            )


def places_pour(
    ownership: HostOwnership,
    guests: list[HostGuest],
    utilisation: dict[str, int],
    login: str,
) -> int | None:
    """Nombre de workspaces que ce compte peut encore créer ici.

    `None` = illimité (aucun plafond de machine, et pas de sous-limite).
    Sert à l'affichage : l'UI doit pouvoir dire « 2 places restantes » sans
    tenter une création pour le découvrir.
    """
    if login not in logins_autorises(ownership, guests):
        return 0

    restant_machine = capacite_restante(ownership, sum(utilisation.values()))

    invite = next((g for g in guests if g.actif and g.login == login), None)
    if invite is None or invite.allocated_workspaces is None:
        return restant_machine

    restant_invite = max(0, invite.allocated_workspaces - utilisation.get(login, 0))
    if restant_machine is None:
        return restant_invite
    return min(restant_machine, restant_invite)
