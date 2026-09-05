# renouvellement — reçu de reconduction

Déclencheur : événement `renouvellement` (état reste `actif`). Un reçu, pas une
relance : le prélèvement a déjà réussi.

**Objet :** Reçu — {{ .Tx.Data.offre_label }}, {{ .Tx.Data.prix_formate }} le {{ .Tx.Data.paiement_date }}

```
Bonjour {{ .Tx.Data.prenom_ou_login }},

Votre abonnement {{ .Tx.Data.offre_label }} a été reconduit :
{{ .Tx.Data.prix_formate }} prélevés le {{ .Tx.Data.paiement_date }}
({{ .Tx.Data.moyen_paiement }}).

- Facture : {{ .Tx.Data.lien_facture }}
- Prochaine échéance : le {{ .Tx.Data.prochaine_echeance_date }}
- Gérer l'abonnement : {{ .Tx.Data.lien_abonnement }}

L'équipe {{ .Tx.Data.produit }}
```

Notes de rédaction :
- volontairement court : c'est un reçu récurrent, il sera lu en diagonale —
  objet auto-suffisant (offre, montant, date) ;
- toujours le chemin de résiliation à un clic : c'est ce qui distingue un
  abonnement honnête d'un abonnement piège, et ça réduit les chargebacks
  (fiche « Remboursements et litiges »).
