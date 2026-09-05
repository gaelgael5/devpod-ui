# resiliation — confirmée, et réversible

Déclencheur : événement `resiliation` (état → `resilie`). Une résiliation n'est
PAS une suppression de compte — le code tient la distinction
(`billing/subscriptions.py`), le mail aussi. Délai de rétention :
`resiliation_jours` (défaut 30).

**Objet :** Votre abonnement {{ .Tx.Data.offre_label }} est résilié — vos données restent récupérables jusqu'au {{ .Tx.Data.date_limite_recuperation }}

```
Bonjour {{ .Tx.Data.prenom_ou_login }},

C'est confirmé : votre abonnement {{ .Tx.Data.offre_label }} est résilié
{{ if .Tx.Data.fin_acces_date }}et votre accès reste ouvert jusqu'au
{{ .Tx.Data.fin_acces_date }}, déjà payé{{ else }}à effet immédiat{{ end }}.
Aucun prélèvement n'aura plus lieu.

Ce qui se passe ensuite :
- votre compte reste ouvert — résilier n'est pas supprimer son compte ;
- vos workspaces sont arrêtés{{ if .Tx.Data.fin_acces_date }} au
  {{ .Tx.Data.fin_acces_date }}{{ end }}, PAS supprimés ;
- tout reste récupérable jusqu'au {{ .Tx.Data.date_limite_recuperation }}
  ({{ .Tx.Data.recuperation_jours }} jours).

Vous changez d'avis ? Une résiliation est réversible : re-souscrivez avant le
{{ .Tx.Data.date_limite_recuperation }} et vous retrouvez vos workspaces
exactement comme vous les avez laissés : {{ .Tx.Data.lien_offres }}

Si quelque chose vous a déplu, dites-le-nous — ça nous aide vraiment :
{{ .Tx.Data.email_support }}.

L'équipe {{ .Tx.Data.produit }}
```

Notes de rédaction :
- le chemin de reprise est le cœur du message (exigence du ticket : « une
  résiliation est réversible ») — il donne la date, le lien, et la promesse
  précise (« exactement comme vous les avez laissés ») ;
- aucun ton culpabilisant, une seule sollicitation de feedback, pas de
  « dernière chance » commerciale ;
- `fin_acces_date` distingue résiliation à échéance (accès payé jusqu'au bout)
  et résiliation immédiate.
