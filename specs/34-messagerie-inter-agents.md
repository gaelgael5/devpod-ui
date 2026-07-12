# Spec 34 — Messagerie inter-agents avec délivrance pilotée

> Statut : implémentée (migration 049)
> Repo : devpod-ui
>
> Décisions d'implémentation (latitude §2 « FK à trancher ») : référence de workspace par
> ws_id texte "{login}-{name}" (workspaces.id entier est réattribué à chaque save de config,
> inutilisable en FK stable), pas de FK dure ; id de message = uuid4 texte. La couche MCP ne
> connaît que owner_login (pas de workspace émetteur ambiant) → message_send prend un
> `from_workspace` explicite. v1 intra-utilisateur. Routes montées sous /me/agent-messages
> (convention codebase) plutôt que /api. Corps rendu en texte préformaté (pas de markdown v1).

## 1. Contexte et objectif

Les agents Claude Code s'exécutent dans des workspaces isolés. Certaines tâches nécessitent
qu'un agent sollicite un autre agent (question sur un contrat d'API, demande de revue,
dépendance bloquante entre deux repos).

Cette spec introduit une messagerie asynchrone inter-agents dont la délivrance est
**exclusivement pilotée par l'utilisateur** : un agent pousse un message via le gateway MCP,
le message reste en attente, et c'est l'utilisateur qui décide depuis le portail de le
transmettre (ou non) à une session du workspace destinataire.

Principes directeurs :

- **Pas de boucle autonome** : aucun message ne circule d'agent à agent sans action humaine.
  Cohérent avec le paradigme pull (Claude web pilote, les sessions Claude Code exécutent).
- **Fire-and-forget côté émetteur** : après l'envoi, l'agent poursuit ses autres tâches.
  Il consigne l'envoi et ce qu'il en attend dans son journal de travail (cf. §7).
- **Destinataire = workspace, pas session** : les sessions sont éphémères ; le choix de la
  session d'injection se fait au moment de la délivrance.

## 2. Modèle de données

Migration additive (numéro à attribuer) — table `agent_messages` :

| Colonne                | Type          | Contraintes                                        |
|------------------------|---------------|----------------------------------------------------|
| `id`                   | `uuid`        | PK, `gen_random_uuid()`                            |
| `created_at`           | `timestamptz` | `NOT NULL DEFAULT now()`                           |
| `from_workspace_id`    | `uuid`        | `NOT NULL`, FK `workspaces(id)`                    |
| `from_session`         | `text`        | `NULL` (nom de la session émettrice si connu)      |
| `to_workspace_id`      | `uuid`        | `NOT NULL`, FK `workspaces(id)`                    |
| `subject`              | `text`        | `NOT NULL`, ≤ 200 caractères (contrainte CHECK)    |
| `body`                 | `text`        | `NOT NULL` (markdown libre, ≤ 20 000 caractères)   |
| `reply_to`             | `uuid`        | `NULL`, FK `agent_messages(id)`                    |
| `status`               | `text`        | `NOT NULL DEFAULT 'pending'`, CHECK ∈ {`pending`, `delivered`, `cancelled`} |
| `delivered_at`         | `timestamptz` | `NULL`                                             |
| `delivered_to_session` | `text`        | `NULL`                                             |
| `cancelled_at`         | `timestamptz` | `NULL`                                             |

Index :

- `idx_agent_messages_to_pending` sur `(to_workspace_id) WHERE status = 'pending'`
  (badge UI et liste de délivrance)
- `idx_agent_messages_from` sur `(from_workspace_id, created_at DESC)`
- `idx_agent_messages_reply_to` sur `(reply_to) WHERE reply_to IS NOT NULL`

Règles :

- `from_workspace_id ≠ to_workspace_id` (CHECK) — pas d'auto-envoi.
- Transitions de statut autorisées : `pending → delivered`, `pending → cancelled`.
  Aucune autre transition. Un message délivré est immuable.
- Suppression d'un workspace : aligner le comportement des FK sur la convention en place
  dans les autres tables référençant `workspaces` (à trancher à l'implémentation) ;
  le portail affiche « workspace supprimé » si la jointure échoue.

## 3. Primitives MCP (gateway)

Trois primitives exposées aux agents :

### `devpod__message_send`

Entrée : `to_workspace` (nom ou id), `subject`, `body`, `reply_to?` (uuid).

Comportement :
- Résout le workspace destinataire ; erreur explicite s'il n'existe pas.
- Refuse si `to_workspace` == workspace émetteur.
- Si `reply_to` est fourni : vérifie que le message référencé existe et que le workspace
  émetteur en était le destinataire (on ne répond qu'à un message qu'on a reçu).
- Crée le message en `pending` et retourne :

```json
{
  "message_id": "…",
  "status": "pending",
  "note": "La délivrance nécessite une action de l'utilisateur et n'est ni garantie ni immédiate. Poursuivez vos autres tâches."
}
```

La `note` fait partie du contrat : elle rappelle à l'agent le modèle fire-and-forget
à chaque appel, sans dépendre uniquement de la documentation.

### `devpod__message_status`

Entrée : `message_id`.
Sortie : statut, horodatages, et le cas échéant la liste des `message_id` de réponses
liées (`reply_to = message_id`) avec leur statut.
Restriction : accessible uniquement au workspace émetteur ou destinataire du message.

### `devpod__message_list`

Entrée : `workspace_id?` (défaut : workspace courant), `direction?` ∈ {`received`, `sent`, `all`}
(défaut `received`), `limit?` (défaut 20).
Sortie : pour `received`, uniquement les messages `delivered` (un agent ne voit jamais
les `pending` qui lui sont destinés — la file d'attente appartient à l'utilisateur) ;
pour `sent`, tous ses envois avec statut.

## 4. Endpoints REST (portail)

Sous `/api/agent-messages` :

- `GET /api/agent-messages?status=pending` — liste pour le panneau de délivrance,
  jointure sur les noms de workspaces émetteur/destinataire.
- `GET /api/agent-messages/{id}` — détail (corps complet, fil `reply_to`).
- `POST /api/agent-messages/{id}/deliver` — corps : `{ "session": "…" }`.
  Voir §5 pour le déroulé. Réponses : `200` (délivré), `409` (session occupée ou
  message non-`pending`), `404` (session introuvable).
- `POST /api/agent-messages/{id}/cancel` — passe en `cancelled`. `409` si non-`pending`.

Pas d'endpoint de création côté REST : seule la voie MCP crée des messages.

## 5. Mécanisme de délivrance

Au clic sur « Transmettre » avec une session cible choisie :

1. Vérification que le message est toujours `pending` (verrou optimiste :
   `UPDATE … WHERE status = 'pending'` et contrôle du rowcount).
2. `session_get` sur la session cible : si `processing = true`, abandon avec `409`
   et message UI « Session occupée — réessayer quand l'agent aura rendu la main ».
   On n'injecte jamais dans le stdin d'un agent en plein travail.
3. `session_send` avec le template de framing :

```
[Message inter-agent — de {from_workspace} — id {message_id}]
Sujet : {subject}

{body}

Pour répondre, utiliser devpod__message_send avec reply_to="{message_id}".
La réponse sera transmise à l'émetteur après validation par l'utilisateur.
```

4. Passage en `delivered` avec `delivered_at` et `delivered_to_session`.

Si l'étape 3 échoue (session morte entre-temps), le message reste `pending` et
l'erreur est remontée à l'UI. L'ordre vérification → injection → commit garantit
qu'un message marqué `delivered` a réellement été injecté ; le cas résiduel
(injection réussie, commit échoué) est accepté comme rare et sans gravité —
une re-délivrance manuelle produirait un doublon visible, pas une corruption.

## 6. UI — page workspaces

- **Badge compteur** sur chaque carte de workspace : nombre de messages `pending`
  entrants (icône enveloppe). Optionnel : indicateur discret des envois `pending` sortants.
- **Panneau « Demandes inter-agents »** (accessible depuis le badge ou un onglet global) :
  - Liste des `pending` : émetteur → destinataire, sujet, extrait du corps, ancienneté.
  - Détail au clic : corps complet (rendu markdown), fil de la conversation si `reply_to`.
  - Sélecteur de session cible parmi les sessions actives du workspace destinataire —
    pré-sélectionnée s'il n'y en a qu'une. Si aucune session active : bouton désactivé
    avec mention « Aucune session active — ouvrir une session pour transmettre ».
  - Boutons : **Transmettre** / **Rejeter**.
- Rafraîchissement par polling TanStack Query (intervalle aligné sur l'existant du portail),
  pas de nouveau canal temps réel pour la v1.
- Composants ≤ 300 lignes : prévoir `AgentMessagesPanel`, `AgentMessageDetail`,
  `AgentMessageDeliverDialog` distincts.

## 7. Contrat documentaire côté agent

À ajouter dans la documentation injectée aux agents (CLAUDE.md des workspaces ou
équivalent) :

- Après un `message_send`, l'agent **consigne dans son journal de travail** : l'id du
  message, le destinataire, ce qui est attendu en retour, et l'impact sur ses tâches
  (bloquant / non bloquant).
- L'agent **ne fait pas de polling** sur `message_status` et n'attend pas la réponse :
  il poursuit ses autres tâches ou rend la main. La réponse éventuelle lui parviendra
  comme un message entrant injecté par l'utilisateur.
- Si une tâche est bloquée par l'attente d'une réponse, l'agent le signale explicitement
  en fin de tour pour que le pilote puisse séquencer.

## 8. Cas limites

- **Workspace destinataire arrêté** : l'envoi reste possible (le message attend) ;
  la délivrance exige une session active.
- **Message `pending` vers un workspace supprimé** : affiché avec mention explicite,
  seul « Rejeter » reste disponible.
- **Doublons** : pas de déduplication en v1 ; le gate humain suffit (l'utilisateur
  voit et rejette les doublons).
- **Chaîne de réponses** : `reply_to` permet des fils linéaires A→B→A→B ; chaque maillon
  repasse par la validation utilisateur — profondeur non limitée mais toujours gated.

## 9. Hors périmètre v1

- Délivrance automatique ou règles d'auto-approbation.
- Corps structuré (types de demande, références de fichiers formalisées).
- Notifications externes (mail, Slack) sur nouveau message `pending`.
- Dépôt en mode passif dans `workspace_messages` (option B du cadrage) — réévaluable
  si le besoin d'une découverte pull par l'agent apparaît.
- Purge/rétention des messages anciens.
