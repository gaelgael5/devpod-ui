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


class PolitiqueRetention(BaseModel):
    """Combien de temps un workspace non payé survit avant destruction.

    Sur `echec_paiement` et `resiliation`, le workspace est ARRÊTÉ, pas détruit
    — le disque reste sur le host. La destruction n'intervient qu'à l'expiration
    d'un délai propre à chaque type d'événement : c'est la seule règle du lot
    qui efface des données, et le délai est ce qui laisse au client le temps
    d'archiver ou de reprendre.

    Défauts PROVISOIRES (les valeurs définitives restent à cadrer sur la
    fiche) : volontairement longs — se tromper vers le haut coûte du disque,
    se tromper vers le bas coûte le travail d'un client.
    """

    model_config = ConfigDict(extra="forbid")

    #: Jours entre le passage en échec de paiement et la destruction.
    echec_paiement_jours: int = Field(default=14, ge=1)
    #: Jours entre la résiliation et la destruction.
    resiliation_jours: int = Field(default=30, ge=1)
    #: Jours AVANT la destruction où part le dernier avertissement email
    #: (fiche 6fdfdaab). 0 = pas d'avertissement — c'est le « seulement si le
    #: délai configuré est > 0 » de la fiche.
    avertissement_jours: int = Field(default=3, ge=0)

    def delai_jours(self, state: str) -> int:
        """Délai applicable à un état d'abonnement en fin de vie.

        Table exhaustive sur les deux états surveillés : un état inconnu est une
        faute de programmation, pas un délai par défaut silencieux.
        """
        par_etat = {
            "echec_paiement": self.echec_paiement_jours,
            "resilie": self.resiliation_jours,
        }
        if state not in par_etat:
            raise ValueError(f"pas de délai de rétention pour l'état {state!r}")
        return par_etat[state]


class BillingConfig(BaseModel):
    """Réglages de facturation de l'installation."""

    model_config = ConfigDict(extra="forbid")

    relance: PolitiqueRelance = Field(default_factory=PolitiqueRelance)
    retention: PolitiqueRetention = Field(default_factory=PolitiqueRetention)
