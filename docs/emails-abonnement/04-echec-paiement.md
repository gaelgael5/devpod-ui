# echec_paiement — ce qui est arrêté, ce qui reste récupérable

Déclencheur : événement `echec_paiement` (état → `echec_paiement`). Le délai de
récupération vient de la politique de rétention (`echec_paiement_jours`,
défaut 14).

**Objet :** Action requise — le paiement de votre abonnement {{ .Tx.Data.offre_label }} a échoué

```
Bonjour {{ .Tx.Data.prenom_ou_login }},

Le prélèvement de {{ .Tx.Data.prix_formate }} du {{ .Tx.Data.echec_date }}
n'a pas abouti{{ if .Tx.Data.echec_motif }} ({{ .Tx.Data.echec_motif }}){{ end }}.

Ce que ça change dès maintenant :
- vos workspaces sont arrêtés — ils ne sont PAS supprimés ;
- vos données, dépôts et configurations sont intacts.

Ce qui reste récupérable, et jusqu'à quand :
- tout, jusqu'au {{ .Tx.Data.date_limite_recuperation }}
  ({{ .Tx.Data.recuperation_jours }} jours) ;
- mettre à jour votre moyen de paiement rétablit l'accès immédiatement :
  {{ .Tx.Data.lien_paiement }}

Après le {{ .Tx.Data.date_limite_recuperation }}, vos workspaces
{{ if .Tx.Data.avertissement_avant_destruction }}seront supprimés — vous
recevrez un dernier avertissement avant{{ else }}seront supprimés
définitivement{{ end }}.

Un souci avec le paiement ? Répondez-nous : {{ .Tx.Data.email_support }}.

L'équipe {{ .Tx.Data.produit }}
```

Notes de rédaction :
- la distinction arrêté / supprimé est LA phrase importante du mail — le code
  la tient (rétention), le vocabulaire doit la tenir aussi ;
- la date limite est absolue (jamais « dans 14 jours » seul) : le mail sera
  relu plus tard ;
- le motif d'échec vient du canal de vente et peut être absent — conditionnel ;
- l'annonce du dernier avertissement dépend du délai configuré (> 0).
