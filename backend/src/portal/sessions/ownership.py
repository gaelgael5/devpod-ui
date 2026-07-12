"""Résolution de l'owner effectif d'une opération de session.

Par défaut une opération de session porte sur le conteneur de l'appelant. Un
admin peut cibler le conteneur d'un **autre** user en passant `owner`
explicitement ; un non-admin qui tente la même chose est refusé. Le login ciblé
est validé (DNS-safe) avant tout usage en `ws_id` / chemin.
"""

from __future__ import annotations

from ..auth.rbac import validate_username
from ..settings import get_settings


class OwnershipDenied(Exception):
    """Un non-admin a demandé le conteneur d'un autre user."""


def resolve_owner(*, login: str, roles: list[str], owner: str | None) -> str:
    """Owner effectif : l'appelant, sauf si un admin cible un autre user.

    - `owner` absent ou égal à `login` → `login` (cas nominal, aucun privilège
      requis) ;
    - `owner` différent → exige le rôle admin (sinon `OwnershipDenied`), puis
      valide le login ciblé (`UsernameError` si non conforme) avant de le
      renvoyer.
    """
    if not owner or owner == login:
        return login
    if get_settings().oidc_admin_role not in roles:
        raise OwnershipDenied(owner)
    return validate_username(owner)
