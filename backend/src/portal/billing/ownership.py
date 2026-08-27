"""Propriété d'une machine dédiée, invités, et quota de workspaces.

Le point structurant, celui qui se trompe facilement : **`max_workspaces` est la
capacité de LA MACHINE, pas un quota individuel toutes machines confondues.**
Une machine provisionnée par un forfait à 5 workspaces accepte 5 workspaces en
tout, répartis entre son propriétaire et les invités qu'il a conviés. Un invité
peut recevoir une sous-limite ; le propriétaire, lui, consomme ce qui reste.

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
    """Rattachement d'une machine à son propriétaire.

    `max_workspaces` est un instantané du quota de l'offre qui a provisionné la
    machine : celle-ci a été dimensionnée pour ce quota, un changement de
    catalogue ne la redimensionne pas rétroactivement. `None` = illimité.
    """

    model_config = ConfigDict(extra="forbid")

    host_name: str
    owner_login: str
    hosting_type: HostingType = "dedie"
    offer_slug: str | None = None
    max_workspaces: int | None = Field(default=None, ge=0)


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


def capacite_restante(ownership: HostOwnership, utilises: int) -> int | None:
    """Places libres sur la machine, `None` si la capacité est illimitée."""
    if ownership.max_workspaces is None:
        return None
    return max(0, ownership.max_workspaces - utilises)


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
    2. la capacité de la machine est atteinte — elle prime sur tout le reste,
       c'est la limite physique payée ;
    3. l'invité a une sous-limite et l'a atteinte.
    """
    if login not in logins_autorises(ownership, guests):
        raise QuotaDepasse(
            f"{login} n'est ni propriétaire ni invité de la machine {ownership.host_name}"
        )

    total = sum(utilisation.values())
    restant = capacite_restante(ownership, total)
    if restant is not None and restant <= 0:
        raise QuotaDepasse(
            f"capacité de la machine {ownership.host_name} atteinte "
            f"({total}/{ownership.max_workspaces} workspaces)"
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

    `None` = illimité (capacité de machine illimitée et pas de sous-limite).
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
