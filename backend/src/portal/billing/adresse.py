"""L'adresse de facturation : structurée, et muette dans les journaux.

Structurée parce que le canal de vente l'attend ainsi (`line1`, `city`,
`postal_code`, `country`…) : une adresse en texte libre obligerait à la découper
au moment de payer, et c'est là qu'on se trompe.

Muette parce qu'une adresse est une donnée personnelle SANS être un secret au
sens du résolveur : la redaction automatique du portail ne la couvre pas. La
protection est donc portée par le type lui-même — `repr()` et `str()` ne
montrent que le pays. Un log accidentel du modèle ne fuit pas l'adresse ;
seuls `model_dump()`/`model_dump_json()` , appelés exprès, la donnent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AdresseFacturation(BaseModel):
    """Adresse structurée, alignée sur ce que Stripe attend d'un client."""

    model_config = ConfigDict(extra="forbid")

    line1: str = Field(min_length=1, max_length=200)
    line2: str = Field(default="", max_length=200)
    city: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=1, max_length=20)
    #: Région/État — vide hors des pays qui en ont besoin (US, CA…).
    state: str = Field(default="", max_length=100)
    #: ISO 3166-1 alpha-2. C'est LUI qui doit coïncider avec le pays de la
    #: souscription : deux pays qui divergent produiraient une facture dont le
    #: pays contredit l'adresse imprimée dessus.
    country: str = Field(pattern=r"^[A-Z]{2}$")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"AdresseFacturation(country={self.country!r}, …masquée…)"

    __str__ = __repr__
