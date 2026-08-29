"""Répartition d'un quota d'abonnement sur les machines qui l'hébergent.

Un abonnement donne droit à un nombre de workspaces. Ces workspaces ne vivent
pas forcément sur une seule machine : le pool mutualisé peut en poser trois ici
et deux là. Chaque rattachement porte donc une PART, et la somme des parts d'un
abonnement ne dépasse pas son quota.

Deux plafonds distincts s'appliquent, et leur ordre n'est pas négociable :

1. **La capacité de la machine prime.** Limite physique : au-delà, la machine
   plante. Aucun forfait ne la relève — on n'achète pas de la RAM avec un
   abonnement.
2. **Le quota du forfait** vient ensuite. C'est une limite commerciale, et le
   dire explicitement change le conseil qu'on donne : « capacité atteinte »
   appelle une machine plus grosse, « quota atteint » appelle un forfait
   supérieur. Les confondre envoie l'utilisateur payer pour rien.

Module PUR : il ne lit pas la base, il reçoit l'état et rend un verdict. Ce qui
le rend testable sans base, et donne un message d'erreur affichable tel quel.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QuotaDepasse(Exception):
    """Le rattachement est refusé (message FR, affichable)."""


class Part(BaseModel):
    """Ce qu'un abonnement a obtenu sur UNE machine.

    `allocated_workspaces` est strictement positif : une part de zéro n'est pas
    une part, c'est l'absence de rattachement — et la laisser exister ferait
    croire à une machine associée sur laquelle rien ne peut tourner.
    """

    model_config = ConfigDict(extra="forbid")

    host_name: str
    allocated_workspaces: int = Field(gt=0)


def parts_disponibles(quota_forfait: int | None, parts: list[Part]) -> int | None:
    """Workspaces encore attribuables sur ce quota. `None` = quota illimité.

    Jamais négatif : un quota déjà dépassé — offre abaissée, reprise manuelle —
    rend 0. Rendre un négatif ferait passer un `> 0` ailleurs pour une réserve.
    """
    if quota_forfait is None:
        return None
    return max(0, quota_forfait - sum(p.allocated_workspaces for p in parts))


def verifier_part(
    quota_forfait: int | None,
    parts: list[Part],
    host_name: str,
    demande: int,
    capacite_restante: int | None,
) -> None:
    """Vérifie qu'on peut porter à `demande` la part de cet abonnement sur cette machine.

    `parts` = les parts DÉJÀ posées par cet abonnement, celle de `host_name`
    comprise si elle existe : reposer sur la même machine REMPLACE la part, ne
    l'ajoute pas. Sans cette règle, un webhook rejoué — la norme, pas
    l'exception — épuiserait le quota d'un abonné qui n'a rien demandé.

    `capacite_restante` = places libres sur la machine, hors part actuelle de cet
    abonnement. `None` = capacité non renseignée : on refuse. Poser dessus
    reviendrait à parier sur la RAM d'une machine dont personne n'a dit ce
    qu'elle tient.

    Lève `QuotaDepasse`, ou ne fait rien.
    """
    if capacite_restante is None:
        raise QuotaDepasse(
            f"capacité de la machine {host_name} inconnue : renseignez-la avant "
            "d'y placer des workspaces"
        )
    if demande > capacite_restante:
        raise QuotaDepasse(
            f"capacité de la machine {host_name} atteinte "
            f"({demande} demandés, {capacite_restante} disponibles) : elle ne peut pas "
            "en faire tourner davantage sans planter"
        )

    if quota_forfait is None:
        return
    autres = [p for p in parts if p.host_name != host_name]
    total = sum(p.allocated_workspaces for p in autres) + demande
    if total > quota_forfait:
        raise QuotaDepasse(
            f"quota du forfait atteint ({total}/{quota_forfait} workspaces) : "
            "un forfait supérieur est nécessaire"
        )
