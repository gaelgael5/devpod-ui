"""Paramètres de facturation réglables par l'administrateur.

Séparé des modèles métier : ce sont des réglages d'exploitation, ils vivent dans
la configuration du portail (`GlobalConfig.billing`) et non en base, parce qu'ils
valent pour l'installation entière et non pour un abonné.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PolitiqueRelance(BaseModel):
    """Combien de fois, et à quel rythme, on retente un prélèvement refusé.

    Un prélèvement échoue souvent pour une raison passagère — plafond mensuel
    atteint, carte expirée le matin même. Couper au premier refus perd un client
    qui n'a rien fait de mal ; relancer indéfiniment fait durer un service non
    payé. D'où deux tentatives par défaut, espacées de 24 h : une relance, puis
    on coupe.

    « Couper » signifie ici RÉSILIER, donc de façon réversible : le compte
    demeure et l'abonné peut reprendre quand son moyen de paiement est réglé.
    """

    model_config = ConfigDict(extra="forbid")

    #: Délai avant la relance, en heures.
    delai_heures: int = Field(default=24, gt=0)
    #: Nombre TOTAL de tentatives, relance comprise. 2 = un essai, une relance.
    tentatives_max: int = Field(default=2, ge=1)


class BillingConfig(BaseModel):
    """Réglages de facturation de l'installation."""

    model_config = ConfigDict(extra="forbid")

    relance: PolitiqueRelance = Field(default_factory=PolitiqueRelance)
