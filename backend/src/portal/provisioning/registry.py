"""Enregistrement des drivers embarqués.

Appelé au démarrage du portail (lifespan) ; les tests l'appellent directement.
Les drivers tiers restent possibles via `register_driver` avec un
`ExecutableDriver` pointant sur leur exécutable.
"""

from __future__ import annotations

from .driver import register_driver
from .existing import ExistingMachineDriver


def register_builtin_drivers() -> None:
    register_driver("existing", ExistingMachineDriver())
