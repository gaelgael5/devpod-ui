# Guide agents IA / MCP — workspace-portal

> Documentation générée le 2026-07-05 depuis le code (`backend/src/portal/mcp/`,
> `events/`, `automation/`) et les specs 23/24/25/34. Public : développeur ou agent IA
> (Claude Code, Codex, aider…) qui pilote des workspaces via la passerelle MCP du
> portail.

## 1. Se connecter à la passerelle

La passerelle MCP fédère le serveur intégré **DevPod workspaces** (préfixe d'outils
`devpod__`) et les serveurs externes enregistrés par l'utilisateur. Endpoint :

```
http(s)://<portail>/mcp        (transport streamable_http)
```

Deux modes d'authentification :

**Clé API (`mcpk_…`)** — pour Claude Desktop, scripts, clients headless. À émettre dans
*Services & Sécurité → MCP → Clés API client* ; la page fournit le bloc de configuration
prêt à coller :

```json
{
  "mcpServers": {
    "devpod": {
      "url": "http://<portail>/mcp",
      "headers": { "Authorization": "Bearer <YOUR_APIKEY>" }
    }
  }
}
```

![Clés API client](../user_manuals/images/61-mcp-cles-api.png)

**OAuth** — pour Claude.ai / OpenAI / Gemini / Mistral : ajouter l'URL de la passerelle
comme connecteur personnalisé, s'authentifier via Keycloak, choisir le profil MCP sur
l'écran de consentement. Tokens courts, renouvelés automatiquement, aucune apikey :

![Connexion OAuth](../user_manuals/images/62-mcp-oauth.png)

Dans les deux cas, la clé ou la session est liée à un **profil MCP** qui borne les
services et outils accessibles.

## 2. Inventaire des outils `devpod__*`

45 outils, listés avec description et niveau d'impact dans l'UI
(*MCP → Serveurs MCP → Voir les outils*) :

![Liste des outils](../user_manuals/images/63-mcp-tools-list.png)

Chaque outil annonce son impact : `read-only` (aucune mutation), `write-safe` (écriture
sans casse), `non-destructive`, `destructive-sessions` (coupe les sessions en cours),
`destructive-data` (irréversible, exige `confirm=true`).

### Workspaces (`workspace_*`)

| Outil | Impact | Usage |
|-------|--------|-------|
| `workspace_list` | read | liste, filtre `status` (`running`/`stopped`/`all`) |
| `workspace_get` | read | descripteur complet (repo, branche, node, sessions) |
| `workspace_status` | read | état conteneur + agent |
| `workspace_create` | admin, async | crée (name, repo, branch, recipes[], profile, node_id…) → `op_id` |
| `workspace_delete` | destructive-data | exige `confirm=true` |
| `workspace_stop` / `workspace_restart` | destructive-sessions | arrêt / redémarrage |
| `workspace_reconnect` | non-destructive | `devpod up` idempotent |
| `workspace_apply_recipe` | destructive-sessions | applique une recette |
| `workspace_logs` | read | source `setup` / `agent` / `container` |
| `workspace_resources` | read | CPU, mémoire, disque |
| `workspace_exec` | write-safe | commande non interactive, `timeout_s` |
| `workspace_tree` / `workspace_read_file` / `workspace_write_file` / `workspace_mkdir` | read/write | fichiers — chemins **relatifs à la racine du workspace**, `..` et chemins absolus rejetés ; écriture atomique |
| `workspace_messages` | read | messages contextuels : services mis à disposition, ports, alias SSH |
| `workspace_git_status` / `workspace_git_commit` | read / write-safe | statut, commit conventionnel, push optionnel |
| `workspace_profile_set` | destructive-sessions | change le profil VS Code |
| `workspace_secrets_list` / `workspace_secrets_bind` | read / write-safe | noms de références uniquement (jamais les valeurs) ; liaison réf → variable d'env |

### Sessions terminal (`session_*`)

Sessions tmux persistantes ; **aucun état implicite** : chaque appel précise
`workspace` + `session`.

| Outil | Usage |
|-------|-------|
| `session_list` / `session_get` | sessions actives ; `session_get` renvoie les métadonnées, dont `processing` (la session est-elle occupée) |
| `session_open` | crée la session et lance la commande (agent, REPL…) |
| `session_send` | envoie du texte sur stdin — **n'attend pas la sortie** |
| `session_capture` | lit le buffer du pane (brut, ANSI compris), param `lines` |
| `session_interrupt` | Ctrl-C |
| `session_close` | ferme la session |

Pattern type :

```
workspace_get(ws) → workspace_messages(ws)          # contexte
session_open(ws, "claude", name="main")             # démarrer l'agent
session_send(ws, "…", session="main")               # dialoguer
session_capture(ws, session="main", lines=200)      # lire la réponse
workspace_exec(ws, "npm test")                      # commande one-shot hors session
```

### Opérations asynchrones (`operations_*`)

Les outils `async` (create, delete, restart…) renvoient un `op_id`.
`operations_get(op_id)` donne état/progression/résultat ; `operations_list` filtre par
workspace. **Ne pas poller en boucle** — consulter ponctuellement, ou continuer et
vérifier plus tard.

### Autres familles

- `node_list` (read) — hôtes Docker, options `include=[workload|capacity|load|docker]`.
- `compose_service_*` (9 outils) — cycle de vie des déploiements Docker Compose
  (`start`, `stop`, `restart`, `status`, `logs`, `list`, `down` avec `confirm=true`) et
  templates (`compose_template_list/get/create/update`).
- `logs_query` (read) — logs centralisés Loki : filtres structurés
  (`host`, `role`, `project`, `service`, `unit`, `job`, `level`, `since`, `limit`) ou
  LogQL brut via `query`.
- `portal_reload` (admin) — reconnexion après mise à jour du portail.

## 3. Messagerie inter-agents (spec 34)

Sollicite un agent d'un **autre workspace** (même propriétaire). La délivrance est
**pilotée par l'utilisateur** : le message reste `pending` jusqu'à ce qu'il le
transmette depuis le portail vers une session du destinataire.

```python
message_send(
    from_workspace="mon-ws",      # obligatoire : le workspace où JE tourne
    to_workspace="autre-ws",
    subject="…",                  # ≤ 200 caractères
    body="…",                     # ≤ 20 000 caractères, markdown libre
    reply_to="<message_id>",      # uniquement pour répondre à un message REÇU
)
# → { "message_id": "…", "status": "pending", "note": "fire-and-forget" }
```

Contrat côté agent — à respecter strictement :

1. **Fire-and-forget** : après `message_send`, consigner dans son journal de travail
   l'id du message, le destinataire, ce qu'on attend en retour et l'impact
   (bloquant / non bloquant). Puis poursuivre ses autres tâches ou rendre la main.
2. **Jamais de polling** sur `message_status` : la réponse arrivera comme un message
   entrant injecté dans la session par l'utilisateur.
3. Si une tâche est **bloquée** par l'attente, le signaler explicitement en fin de tour
   pour que le pilote puisse séquencer.
4. L'auto-envoi (`from_workspace == to_workspace`) est refusé ; `reply_to` n'est valide
   que sur un message dont on était le destinataire.

`message_list(workspace, direction="received")` ne montre que les messages **délivrés**
(les `pending` appartiennent à l'utilisateur). États : `pending → delivered | cancelled`.

Le message délivré arrive dans la session avec un cadre standard :

```
[Message inter-agent — de {from_workspace} — id {message_id}]
Sujet : {subject}

{body}

Pour répondre, utiliser devpod__message_send avec reply_to="{message_id}".
```

## 4. Événements et règles d'automatisation

Le portail émet des événements **après** chaque opération métier réussie (registre
fermé) :

```
workspace.created   workspace.deleted   workspace.stopped   workspace.restarted
session.created     session.closed
test_server.created test_server.deleted
compose_service.started compose_service.stopped
```

Un `AppEvent` porte : `event_id`, `type`, `occurred_at`, `actor` (login ou `system`),
`workspace`, `subject` (payload par type), `correlation_id` (l'`op_id` si asynchrone).
Sémantique **at-least-once**, dispatch asynchrone : les règles doivent être
**idempotentes**.

Une **règle** (configurée dans *Services & Sécurité → Règles*) enchaîne :
sonde (appel MCP) → condition(s) en ET → action(s), avec chaînage possible vers une
règle suivante. Les paramètres JSON acceptent les gabarits `{workspace}`, `{actor}`,
`{event}` et `{subject[clé]}` ; le chemin d'extraction navigue le JSON du retour de
sonde (`a.b.c`, projection sur les listes) ; opérateurs `eq`, `neq`, `contains`,
`not_contains`. La première condition fausse ou la première action en erreur arrête la
règle ; chaque exécution est tracée dans le journal des événements (purge à 24 h).

Voir le [manuel utilisateur, § 4.7](../user_manuals/04-services-et-securite.md#47-règles-dautomatisation)
pour la création via l'UI.

## 5. Secrets dans le workspace (SDK Harpocrate)

Les valeurs de secrets ne transitent jamais par MCP (`workspace_secrets_list` ne
renvoie que des noms). Dans le workspace, on les consomme via liaison à des variables
d'environnement (`workspace_secrets_bind`) ou via le SDK Python embarqué
(`Sdk/harpocrate-0.6.0`) :

```python
from harpocrate import VaultClient

client = VaultClient(token="hrpv_1_…", base_url="https://vault.yoops.org")
value = client.secrets.get("ANTHROPIC_API_KEY")
```

CLI équivalente : `harpocrate-gen list|get|populate-all` (variables `HARPOCRATE_TOKEN`,
`HARPOCRATE_URL`). Le SDK gère aussi la rotation sur 401 (`notify_auth_error`,
`using_secret`).

## 6. Règles d'or pour un agent

- Toujours commencer par `workspace_get` + `workspace_messages` : le second contient le
  contexte injecté (services à disposition, ports, alias SSH).
- Respecter les impacts annoncés : avant un outil `destructive-sessions`, vérifier avec
  `session_list` qu'on ne coupe pas une session active.
- Chemins de fichiers : relatifs à la racine du workspace, jamais `..`.
- `session_get` (métadonnées, `processing`) ≠ `session_capture` (contenu du terminal).
- Pas de polling : ni `message_status`, ni `operations_get` en boucle.
- En cas de doute sur un échec de création : `workspace_logs(source="setup")`.

## 7. Sources

| Sujet | Fichiers |
|-------|----------|
| Registre des outils | `backend/src/portal/mcp/devpod_tools/registry.py` |
| Messagerie | `backend/src/portal/mcp/devpod_tools/agent_message_tools.py`, `specs/34-messagerie-inter-agents.md` |
| Auth passerelle | `backend/src/portal/mcp/asgi_auth.py`, `dispatch_common.py`, `aggregator.py` |
| Événements | `backend/src/portal/events/models.py`, `events/bus.py` |
| Règles | `backend/src/portal/automation/models.py`, `automation/engine.py` |
| Specs | `specs/23-mcp-gateway.md`, `specs/24-mcp-devpod.md`, `specs/25-mcp-devpod-complement.md` |
