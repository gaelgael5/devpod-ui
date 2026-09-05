# debut_essai — bienvenue en essai

Déclencheur : événement `debut_essai` (état → `essai`). Un seul envoi par
souscription.

**Objet :** Votre essai {{ .Tx.Data.offre_label }} est ouvert — jusqu'au {{ .Tx.Data.essai_fin_date }}

```
Bonjour {{ .Tx.Data.prenom_ou_login }},

Votre période d'essai du forfait {{ .Tx.Data.offre_label }} est ouverte.
Elle est gratuite et se termine le {{ .Tx.Data.essai_fin_date }}
({{ .Tx.Data.essai_duree_jours }} jours).

Ce à quoi vous avez accès dès maintenant :
- {{ .Tx.Data.quota_workspaces }} workspace(s) de développement (VS Code
  dans le navigateur, rien à installer) ;
- {{ if .Tx.Data.machine_dediee }}une machine dédiée ({{ .Tx.Data.machine_cpu }} vCPU,
  {{ .Tx.Data.machine_ram_go }} Go de RAM){{ else }}nos machines mutualisées{{ end }} ;
- vos dépôts Git, vos secrets et vos outils IA configurés depuis le portail.

Commencer : {{ .Tx.Data.lien_portail }}

Et le {{ .Tx.Data.essai_fin_date }} ?
{{ if .Tx.Data.tacite_reconduction }}Votre abonnement démarrera automatiquement
au tarif de {{ .Tx.Data.prix_formate }} / {{ .Tx.Data.periodicite }}. Vous pouvez
l'annuler à tout moment avant cette date, en deux clics, sans justification :
{{ .Tx.Data.lien_abonnement }}{{ else }}Rien ne sera facturé : l'essai s'arrête
simplement, et vos données restent récupérables pendant
{{ .Tx.Data.retention_jours }} jours si vous souscrivez ensuite.{{ end }}

Une question ? Répondez à ce message : {{ .Tx.Data.email_support }}.

L'équipe {{ .Tx.Data.produit }}
```

Notes de rédaction :
- la date de fin apparaît **dans l'objet** et deux fois dans le corps — c'est
  l'information que l'utilisateur cherchera plus tard ;
- la reconduction (ou son absence) est dite explicitement AVANT tout paiement,
  avec le chemin d'annulation — obligation légale et confiance ;
- pas de secret, pas de lien signé à durée de vie longue.
