"""Taxonomie des échecs de provisionnement (ticket 6).

La distinction qui compte n'est pas succès/échec, c'est **ce qu'il reste
derrière** :

- `EchecAvantCreation` : rien n'existe — rejouable à l'identique, sans risque ;
- `EchecApresCreation` : une machine existe, configuration incomplète — porte
  **obligatoirement** `provider_ref`, pour reprendre ou détruire proprement ;
- `Indetermine` : l'issue est inconnue (timeout en plein apply, driver tué) —
  intervention humaine, jamais de rejeu automatique : rejouer ici, c'est
  exactement la façon de facturer deux VM.

Contrat des drivers : rendre `provider_ref` **dès que la machine existe**, pas
seulement en cas de succès — c'est ce qui rend `EchecApresCreation` possible.
"""

from __future__ import annotations

from typing import Any, Literal


class DriverError(RuntimeError):
    """Échec d'un driver de provisionnement (raison humaine dans le message)."""


class EchecAvantCreation(DriverError):
    """Rien n'a été créé : le rejeu à l'identique est sans effet de bord."""


class EchecApresCreation(DriverError):
    """Une machine existe. `provider_ref` est ce qui permet de la reprendre ou
    de la détruire — sans lui, c'est une orpheline."""

    def __init__(self, message: str, *, provider_ref: dict[str, Any], provider: str = "") -> None:
        super().__init__(message)
        if not provider_ref:
            raise ValueError("EchecApresCreation exige un provider_ref non vide")
        self.provider_ref = provider_ref
        #: Type de driver qui a créé la machine — permet de la détruire.
        self.provider = provider


class Indetermine(DriverError):
    """Issue inconnue : la ressource a peut-être été créée. Pas de rejeu
    automatique — décision humaine."""


EtatEchec = Literal["echec_avant_creation", "echec_apres_creation", "indetermine"]


def run_state_for(exc: BaseException) -> EtatEchec:
    """État `provisioning_runs` correspondant à un échec d'exécution.

    Une exception hors taxonomie (bug, KeyError...) est classée `indetermine` :
    on ne sait pas ce que l'exécution a laissé derrière elle, et la prudence
    interdit le rejeu automatique.
    """
    if isinstance(exc, EchecApresCreation):
        return "echec_apres_creation"
    if isinstance(exc, EchecAvantCreation):
        return "echec_avant_creation"
    return "indetermine"


def provider_ref_of(exc: BaseException) -> dict[str, Any] | None:
    ref = getattr(exc, "provider_ref", None)
    return ref if isinstance(ref, dict) and ref else None


def provider_of(exc: BaseException) -> str:
    prov = getattr(exc, "provider", "")
    return prov if isinstance(prov, str) else ""
