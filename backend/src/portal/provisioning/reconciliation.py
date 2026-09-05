"""Garde-fous cloud : réconciliation trois sources, coût, TTL (ticket 11).

Deux refus explicites, parce qu'ils sont « bonnes pratiques » partout ailleurs
et des pièges ici :

- **jamais de suppression automatique** : le réconciliateur signale, l'action
  reste humaine. Supprimer sur la foi d'une comparaison marche parfaitement
  jusqu'à la panne de base du portail — jour où TOUT le parc paraît orphelin ;
- **jamais d'arrêt automatique à expiration** : une machine qui disparaît sans
  prévenir est pire qu'une machine qui coûte. Le TTL déclenche une alerte.

Trois sources de vérité, pas deux : le state OpenTofu s'intercale entre le
portail et le provider — une ressource connue du state mais pas du portail se
RATTACHE (elle a été montée par nous), elle ne se supprime pas comme une
orpheline pure.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, ConfigDict

from ..config.models import HostConfig
from .errors import EchecAvantCreation

_log = structlog.get_logger(__name__)

# Estimations GROSSIÈRES €/vCPU/mois (pay-as-you-go Europe, Linux, hors disque)
# — assumées imprécises : elles servent le plafond et l'arbitrage
# dédié/mutualisé, pas la facturation. Réviser à la main, jamais deviner.
_EUR_PAR_VCPU_MOIS: dict[str, float] = {
    "ads_v5": 38.0,  # Dads_v5
    "s_v2": 15.0,  # Bs_v2 (burstable)
}

_SKU_RE = re.compile(r"^Standard_[A-Z](\d+)([a-z_0-9]+)$")


def estimer_cout_eur_mois(instance_size: str) -> float:
    """Estimation grossière depuis le nom de SKU. 0.0 = inconnue (et un log :
    un coût inconnu ne doit pas passer pour un coût nul en silence)."""
    m = _SKU_RE.match(instance_size)
    if m is None:
        _log.warning("cout_sku_inconnu", instance_size=instance_size)
        return 0.0
    vcpus, suffixe = int(m.group(1)), m.group(2)
    for connu, tarif in _EUR_PAR_VCPU_MOIS.items():
        if suffixe.endswith(connu):
            return round(vcpus * tarif, 2)
    _log.warning("cout_famille_inconnue", instance_size=instance_size)
    return 0.0


def verifier_plafond(
    hosts: list[HostConfig], nouvelle_estimation_eur: float, plafond_eur: float
) -> None:
    """Refuse AVANT toute création un provisionnement qui dépasserait le
    plafond — le seul garde-fou contre une boucle de rejeu ou une spec folle.
    Plafond 0 = désactivé (environnements sans provider facturé)."""
    if plafond_eur <= 0:
        return
    encours = sum(h.cost_estimate_eur_month for h in hosts)
    if encours + nouvelle_estimation_eur > plafond_eur:
        raise EchecAvantCreation(
            f"plafond de coût atteint : {encours:.0f} € en cours "
            f"+ {nouvelle_estimation_eur:.0f} € demandés > {plafond_eur:.0f} €/mois "
            "— provisionnement refusé, rien n'a été créé"
        )


class Ecarts(BaseModel):
    """Le résultat d'une réconciliation. AUCUN champ d'action : ce modèle
    signale, il ne porte ni ordre ni suppression."""

    model_config = ConfigDict(extra="forbid")

    #: Chez le provider, inconnues du portail ET du state : coûtent pour rien.
    orphelines: list[str]
    #: Chez le provider ET dans le state, hors portail : montées par nous —
    #: un rattachement suffit, pas une destruction.
    a_rattacher: list[str]
    #: Connues du portail, absentes chez le provider : le portail ment.
    fantomes: list[str]
    #: TTL dépassé : ALERTE, jamais d'arrêt automatique.
    expirees: list[str]
    #: Le provider n'a pas pu être interrogé : on ne conclut RIEN sur les
    #: orphelines (une panne d'API ne rend pas le parc orphelin).
    provider_indisponible: bool = False


def classer_ecarts(
    *,
    portail: set[str],
    state: set[str],
    provider: set[str] | None,
    expirees: list[str] | None = None,
) -> Ecarts:
    """Comparaison pure des trois vues. `provider=None` = injoignable : les
    catégories qui en dépendent restent vides plutôt que fausses."""
    if provider is None:
        return Ecarts(
            orphelines=[],
            a_rattacher=[],
            fantomes=[],
            expirees=sorted(expirees or []),
            provider_indisponible=True,
        )
    return Ecarts(
        orphelines=sorted(provider - portail - state),
        a_rattacher=sorted((provider & state) - portail),
        fantomes=sorted(portail - provider),
        expirees=sorted(expirees or []),
    )


def machines_expirees(hosts: list[HostConfig], maintenant: datetime | None = None) -> list[str]:
    """Les machines dont le TTL est dépassé. Une date illisible compte comme
    expirée : mieux vaut une fausse alerte qu'un coût invisible."""
    now = maintenant or datetime.now(UTC)
    expirees: list[str] = []
    for host in hosts:
        if not host.expires_at:
            continue
        try:
            echeance = datetime.fromisoformat(host.expires_at)
            if echeance.tzinfo is None:
                echeance = echeance.replace(tzinfo=UTC)
        except ValueError:
            _log.warning("ttl_illisible", host=host.name, expires_at=host.expires_at)
            expirees.append(host.name)
            continue
        if echeance <= now:
            expirees.append(host.name)
    return expirees
