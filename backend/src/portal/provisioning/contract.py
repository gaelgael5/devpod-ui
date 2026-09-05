"""MachineSpec / MachineDescriptor — les deux schémas du contrat de driver.

Règle de tri (validée au spike Azure, ticket 3) : un champ n'entre dans la
partie commune que s'il a un sens chez au moins deux providers. Tout le reste
va dans `provider` (spec) ou `provider_ref` (descripteur), sections opaques que
seul le driver du provider concerné sait relire.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Même règle que les scripts de provisionnement : DNS-safe, 2 à 32 caractères.
_MACHINE_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$"


class NetworkSpec(BaseModel):
    """Réseau demandé. `dhcp` partout par défaut ; en `static`, `address` est
    obligatoire (CIDR) et `gateway` est consommée par les providers qui en ont
    besoin (Proxmox) et ignorée par ceux dont le subnet la porte (Azure)."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["dhcp", "static"]
    address: str | None = None
    gateway: str | None = None
    dns: str | None = None

    @model_validator(mode="after")
    def _static_exige_adresse(self) -> NetworkSpec:
        if self.mode == "static" and not self.address:
            raise ValueError("network.mode=static exige network.address (CIDR)")
        return self


class MachineSpec(BaseModel):
    """Demande de machine, en vocabulaire neutre.

    `cpu` / `memory_mb` / `disk_gb` sont une *demande* : chaque driver la
    résout (littéralement sur Proxmox ; au plus petit gabarit suffisant sur un
    cloud à SKU). `disk_gb` est absolu — un driver dont le point de départ est
    un template calcule lui-même le delta.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_MACHINE_NAME_PATTERN)
    cpu: int = Field(gt=0)
    memory_mb: int = Field(gt=0)
    disk_gb: int = Field(gt=0)
    user: str = Field(min_length=1)
    ssh_authorized_keys: list[str] = Field(min_length=1)
    network: NetworkSpec
    # Opaque hors du champ `type` : lu uniquement par le driver correspondant.
    provider: dict[str, Any]

    @field_validator("provider")
    @classmethod
    def _provider_porte_son_type(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v.get("type"), str) or not v["type"]:
            raise ValueError("provider.type (chaîne non vide) est obligatoire")
        return v


class ResolvedResources(BaseModel):
    """Ce que le driver a réellement alloué quand la demande a été arrondie
    (résolution vers un SKU). Absent quand l'allocation est littérale."""

    model_config = ConfigDict(extra="forbid")

    cpu: int = Field(gt=0)
    memory_mb: int = Field(gt=0)
    instance_size: str | None = None


class MachineDescriptor(BaseModel):
    """Machine rendue par un driver.

    - `provider_ref` est **opaque** : le portail le stocke et le repasse tel
      quel au driver du même provider (destruction, actions). Il ne le lit
      jamais, n'en indexe aucun champ. C'est ce qui garde l'épic réversible.
    - `hypervisor` porte la provenance (jamais une contrainte) ; vide = inconnu.
    - **Aucun secret en valeur** : `key_path` est une référence de fichier, le
      mot de passe console passe par un slug Harpocrate.
    - Le `type` de jointure (docker-tls / ssh) n'apparaît pas ici : décider
      comment le portail joint la machine est le domaine du portail.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    address: str
    ssh_user: str
    ssh_port: int = 22
    key_path: str = ""
    provider: str
    provider_ref: dict[str, Any]
    hypervisor: str = ""
    ci_password_secret_slug: str | None = None
    resolved: ResolvedResources | None = None
