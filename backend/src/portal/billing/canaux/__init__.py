"""Adaptateurs de canaux de vente.

Un module par fournisseur. Le contrat qu'ils honorent est dans `billing.canal` ;
aucun d'eux ne doit fuir hors d'ici — le reste du portail parle des cinq
événements du cycle d'abonnement, jamais du vocabulaire d'un fournisseur.
"""

from ..canal import CanalDeVente
from .stripe import CanalStripe

#: Un adaptateur par `PaymentProvider.kind`. Ajouter un canal, c'est ajouter une
#: entrée ici — le reste du portail continue de parler des cinq événements.
#:
#: Le registre vit AVEC les adaptateurs, pas dans une route : la route entrante
#: (webhook) et la route sortante (ouverture de paiement) en ont toutes deux
#: besoin, et le faire porter par l'une obligerait l'autre à l'importer.
CANAUX: dict[str, CanalDeVente] = {"stripe": CanalStripe()}
