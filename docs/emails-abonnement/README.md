# Emails du cycle d'abonnement — exemples et variables

Propositions de rédaction pour la feature « Emails du cycle d'abonnement
(Listmonk) » (fiche 6fdfdaab). Six messages, en syntaxe **transactionnelle
Listmonk** (`POST /api/tx`, Go templates : `{{ .Tx.Data.* }}`) — directement
importables comme templates tx.

| Fichier | Événement déclencheur | État résultant |
|---|---|---|
| `01-debut-essai.md` | `debut_essai` | `essai` |
| `02-activation.md` | `activation` | `actif` |
| `03-renouvellement.md` | `renouvellement` | `actif` |
| `04-echec-paiement.md` | `echec_paiement` | `echec_paiement` |
| `05-resiliation.md` | `resiliation` | `resilie` |
| `06-avertissement-pre-destruction.md` | balayeur de rétention (délai > 0) | — |

`remboursement`, `litige_ouvert`, `litige_clos` : pas de mail tant que les
arbitrages de la fiche « Remboursements et litiges » sont ouverts — ils se
journalisent seulement, comme dans le code.

## Catalogue des variables

Convention : le template est BÊTE — tout formatage (dates localisées, montants,
masquage carte) se fait côté portail, les variables `*_date` et `*_formate`
sont des chaînes prêtes à afficher dans la locale du destinataire.

### Destinataire (routage + en-tête)

| Variable | Type | Source | Mails |
|---|---|---|---|
| `email` (destinataire) | str | ⚠ à garantir : claim OIDC ou profil — un compte **local** n'en a pas forcément | tous |
| `prenom_ou_login` | str | prénom OIDC si connu, sinon `users.login` — le nom de la variable dit le repli | tous |
| `locale` | `fr`/`en` | ⚠ à stocker sur le user (préférence) — sert au **choix du template**, pas au template | routage |

### Offre (billing_offers, résolue dans la locale)

| Variable | Type | Source | Mails |
|---|---|---|---|
| `offre_label` | str | label **i18n** de l'offre, résolu par locale | tous |
| `prix_formate` | str | `amount_minor` + `currency` du prix de la souscription, formatés (`12,00 €`) | 01, 02, 03, 04 |
| `periodicite` | str | libellé localisé (« mois ») | 01, 02 |
| `tacite_reconduction` | bool | `offers.tacite_reconduction` | 01 |
| `quota_workspaces` | int | `offers.max_workspaces` | 01 |
| `machine_dediee` | bool | `hosting_type == "dedie"` | 01, 02 |
| `machine_cpu`, `machine_ram_go` | int | profil machine de l'offre | 01 |

### Cycle de la souscription

| Variable | Type | Source / calcul | Mails |
|---|---|---|---|
| `essai_fin_date`, `essai_duree_jours` | str, int | terme de l'essai (`billing/terme.py`) | 01 |
| `paiement_date` | str | événement du canal de vente | 02, 03 |
| `moyen_paiement` | str | ⚠ à exposer par le canal (« carte •••• 4242 ») — masqué côté portail | 02, 03 |
| `prochaine_echeance_date` | str | terme suivant | 02, 03 |
| `echec_date`, `echec_motif` | str, str? | événement `echec_paiement` — motif **optionnel** (le provider peut se taire) | 04 |
| `fin_acces_date` | str? | résiliation à échéance (accès payé) vs immédiate | 05 |
| `date_limite_recuperation` | str | **calculée à l'envoi** : date événement + `retention.delai_jours(state)` (14 j `echec_paiement`, 30 j `resilie`) | 04, 05 |
| `recuperation_jours` | int | politique de rétention (config) | 04, 05 |
| `avertissement_avant_destruction` | bool | délai configuré > 0 | 04 |
| `etat` | str | `echec_paiement`/`resilie` — choisit le chemin de reprise du 06 | 06 |
| `destruction_date`, `destruction_dans_jours` | str, int | échéance du balayeur, absolue ET relative | 06 |

### Parc de l'utilisateur

| Variable | Type | Source | Mails |
|---|---|---|---|
| `workspaces` | list[str] | noms des workspaces de la souscription — une liste nommée rend la perte concrète | 06 |
| `machine_dediee_nom` | str? | host rattaché à la souscription | 06 |

### Liens et constantes produit (config, pas par-mail)

| Variable | Source |
|---|---|
| `lien_portail`, `lien_abonnement`, `lien_paiement`, `lien_offres` | `server.external_url` + routes fixes du portail |
| `lien_facture` | ⚠ dépend de la facturation légale (feature 4fdc2298, pas livrée) — repli : la page historique d'achats |
| `email_support`, `produit` | ⚠ config à créer (nom commercial, adresse support) |

## Ce que l'évaluation révèle (à traiter au ticket d'implémentation)

1. **L'email du destinataire n'est pas garanti** : un compte en auth locale n'a
   pas de claim OIDC — il faut un champ email au profil (et refuser d'envoyer,
   avec un log, plutôt que d'envoyer à vide).
2. **La locale n'est pas stockée** : préférence utilisateur à ajouter ;
   modélisation Listmonk = **un template tx par (message, locale)**, soit
   6 × 2 = 12 templates, nommés `abonnement/<événement>/<locale>`.
3. **Trois dates se calculent à l'envoi** (`date_limite_recuperation`,
   `destruction_*`, `prochaine_echeance_date`) : elles dépendent de la config
   de rétention au moment T — jamais stockées dans le mail-log, sinon un
   changement de politique rend les mails envoyés mensongers… les figer DANS
   l'événement d'envoi journalisé, précisément pour l'inverse : pouvoir prouver
   ce qui a été annoncé.
4. **`moyen_paiement` et `lien_facture` dépendent de features voisines**
   (canal de vente, facturation légale) : prévoir les deux variables dès le
   payload avec un rendu conditionnel, pour ne pas re-toucher les templates.
5. Payload = dict plat de chaînes + 3 booléens + 1 liste — aucun objet imbriqué,
   aucun secret, aucun montant en centimes bruts.
