"""Contrat de driver de provisionnement (épic hyperviseur-agnostique, ticket 4).

Le portail crée et détruit des machines à travers une paire de schémas
(`MachineSpec` en entrée, `MachineDescriptor` en sortie) et une interface de
driver à deux opérations. Tout ce qui est propre à un provider vit dans les
sections opaques `provider` (spec) et `provider_ref` (descripteur) : le portail
ne les lit jamais, il les stocke et les repasse au driver du même provider.
"""

from __future__ import annotations

from .contract import MachineDescriptor, MachineSpec, NetworkSpec, ResolvedResources
from .driver import (
    DriverError,
    ExecutableDriver,
    ProvisioningDriver,
    driver_for,
    register_driver,
)

__all__ = [
    "DriverError",
    "ExecutableDriver",
    "MachineDescriptor",
    "MachineSpec",
    "NetworkSpec",
    "ProvisioningDriver",
    "ResolvedResources",
    "driver_for",
    "register_driver",
]
