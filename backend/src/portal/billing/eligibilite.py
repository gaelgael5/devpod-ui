"""Peut-on souscrire cette offre, ici et maintenant ?

Module PUR : il ne lit pas la base, il reçoit l'état et rend un verdict. Ce qui
le rend testable sans base ni fournisseur de paiement, et donne un motif de refus
affichable tel quel.

**Éligibilité n'est pas idempotence, et les deux ne doivent pas se mélanger.**

- L'idempotence demande « cet abonnement-ci a-t-il déjà sa machine ? ». Elle
  existe parce que `debut_essai` puis `activation` arrivent pour le même
  abonnement, elle se clé sur `subscription_id`, et elle vit dans
  `db.host_pool.a_deja_une_machine`.
- L'éligibilité demande « ce compte a-t-il le droit de souscrire ceci ? ». C'est
  une question commerciale, posée AVANT que l'abonnement existe.

Élargir la clé d'idempotence pour porter une règle commerciale a déjà produit un
défaut : la seconde souscription d'un compte à la même offre était considérée
comme déjà provisionnée et ne recevait rien, en silence. On ne recommence pas.
"""

from __future__ import annotations

from .models import Offer


class SouscriptionRefusee(Exception):
    """La souscription n'est pas possible (message FR, affichable tel quel)."""


class CanalIndisponible(SouscriptionRefusee):
    """Le canal de paiement de l'offre n'est pas disponible dans ce pays.

    Même refus pour le client, mais une nature différente : ce n'est pas son
    état qui s'y oppose, c'est un TROU DE CONFIGURATION — et une vente perdue.
    L'appelant la distingue pour que la perte remonte côté exploitation au lieu
    d'être subie en silence (ticket « Pays sans canal de paiement »).
    """


def verifier(
    offre: Offer,
    *,
    offres_deja_souscrites: set[str],
    devise: str,
    devises_actives: set[str],
    providers_du_pays: set[str],
    pays: str,
) -> None:
    """Lève `SouscriptionRefusee` si l'offre ne peut pas être souscrite.

    L'ordre des contrôles n'est pas indifférent : on refuse d'abord ce qui tient
    à l'offre elle-même, puis ce qui tient au compte, puis ce qui tient au
    paiement. Un client à qui l'on dit « cette offre n'est plus proposée »
    n'a pas besoin d'apprendre en plus que sa devise ne convient pas.
    """
    if not offre.published:
        raise SouscriptionRefusee("Cette offre n'est plus proposée.")

    if offre.duration_days is None:
        # Le garde-fou de publication l'exige déjà ; on ne s'y fie pas seule.
        # Sans terme, l'échéance ne se calcule pas et l'abonnement ne finirait
        # jamais.
        raise SouscriptionRefusee("Cette offre n'a pas de durée : elle n'est pas souscriptible.")

    if offre.une_par_compte and offre.slug in offres_deja_souscrites:
        raise SouscriptionRefusee(
            "Vous avez déjà souscrit cette offre : elle est limitée à une par compte."
        )

    if devise not in devises_actives:
        raise SouscriptionRefusee(f"La devise {devise} n'est pas acceptée.")

    # Une offre gratuite n'a ni prix ni canal de paiement à honorer : les deux
    # contrôles suivants n'ont pas lieu d'être, et les appliquer refuserait une
    # offre de bienvenue parfaitement valable.
    if offre.is_free:
        return

    if offre.prix(devise) is None:
        raise SouscriptionRefusee(
            f"Cette offre n'a pas de prix en {devise}. Choisissez une autre devise."
        )

    if not offre.provider_slug:
        raise SouscriptionRefusee("Cette offre n'a pas de canal de paiement configuré.")

    # Refus assumé comme provisoire — le client n'y peut rien, c'est un trou de
    # configuration. Voir le ticket « Pays sans canal de paiement ».
    if offre.provider_slug not in providers_du_pays:
        raise CanalIndisponible(
            f"Le moyen de paiement de cette offre n'est pas disponible pour le pays {pays}."
        )
