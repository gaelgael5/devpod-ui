# avertissement pré-destruction — le dernier filet

Déclencheur : le balayeur de rétention, quand une souscription en
`echec_paiement` ou `resilie` approche de sa date de destruction. **Envoyé
seulement si le délai configuré pour l'événement est > 0** (contrat du
ticket). C'est le dernier message avant une perte définitive : son
déclenchement se teste pour lui-même, pas seulement à travers le scheduler.

**Objet :** Dernier rappel — vos workspaces seront supprimés le {{ .Tx.Data.destruction_date }}

```
Bonjour {{ .Tx.Data.prenom_ou_login }},

Dernier rappel, promis : le {{ .Tx.Data.destruction_date }}, soit dans
{{ .Tx.Data.destruction_dans_jours }} jours, vos workspaces et leurs données
seront définitivement supprimés — dépôts non poussés, configurations,
fichiers de travail compris. Cette suppression est irréversible.

Ce qui sera supprimé :
{{ range .Tx.Data.workspaces }}- {{ . }}
{{ end }}{{ if .Tx.Data.machine_dediee_nom }}- votre machine dédiée ({{ .Tx.Data.machine_dediee_nom }})
{{ end }}

Pour tout conserver, il suffit de
{{ if eq .Tx.Data.etat "echec_paiement" }}mettre à jour votre moyen de
paiement : {{ .Tx.Data.lien_paiement }}{{ else }}re-souscrire :
{{ .Tx.Data.lien_offres }}{{ end }}
L'accès est rétabli immédiatement, rien n'est perdu.

Vous préférez récupérer vos fichiers sans re-souscrire ? Répondez à ce
message avant le {{ .Tx.Data.destruction_date }} : {{ .Tx.Data.email_support }}.

L'équipe {{ .Tx.Data.produit }}
```

Notes de rédaction :
- l'objet porte la date et le mot « supprimés » — ce mail doit être ouvert ;
- la liste NOMMÉE des workspaces rend la perte concrète (une liste vaut mieux
  qu'un compte) ;
- « dernier rappel, promis » : c'est vrai (un seul envoi), et ça se distingue
  du harcèlement commercial ;
- une porte de sortie non commerciale (récupérer ses fichiers) — le but est de
  ne jamais détruire les données de quelqu'un qui les voulait ;
- le chemin de reprise dépend de l'état (`echec_paiement` → paiement,
  `resilie` → re-souscription).
