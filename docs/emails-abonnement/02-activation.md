# activation — bascule en facturation réelle

Déclencheur : événement `activation` (état → `actif`). Premier paiement
confirmé par le canal de vente.

**Objet :** Votre abonnement {{ .Tx.Data.offre_label }} est actif

```
Bonjour {{ .Tx.Data.prenom_ou_login }},

Votre abonnement {{ .Tx.Data.offre_label }} est actif : le paiement de
{{ .Tx.Data.prix_formate }} a bien été reçu le {{ .Tx.Data.paiement_date }}
({{ .Tx.Data.moyen_paiement }}).

L'essentiel :
- prochaine échéance : le {{ .Tx.Data.prochaine_echeance_date }}, même montant,
  prélevé automatiquement ;
- votre facture : {{ .Tx.Data.lien_facture }}
- gérer l'abonnement (moyen de paiement, résiliation) :
  {{ .Tx.Data.lien_abonnement }}

{{ if .Tx.Data.machine_dediee }}Votre machine dédiée reste la même que pendant
l'essai — rien ne change dans vos workspaces.{{ end }}

Merci de votre confiance,
L'équipe {{ .Tx.Data.produit }}
```

Notes de rédaction :
- le triplet montant / date / moyen de paiement est ce qui évite le
  « c'est quoi ce prélèvement ? » et les litiges ;
- la facture est un lien vers le portail (numérotation légale, feature
  4fdc2298), jamais une pièce jointe générée à l'envoi ;
- pas de « bienvenue » : l'utilisateur est déjà là depuis l'essai.
