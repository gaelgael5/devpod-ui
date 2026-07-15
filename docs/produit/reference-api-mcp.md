# Référence API & MCP

Deux surfaces programmatiques : l'**API REST** (utilisée par le frontend, sous
session OIDC) et les **outils MCP `devpod`** (utilisés par les agents).

> Toutes les routes `/me/*` requièrent une **session** (cookie OIDC). Les modèles
> pydantic sont en `extra="forbid"` : n'envoyer que les champs documentés.

## API REST — routeurs & préfixes

| Domaine | Préfixe | Exemples |
|---------|---------|----------|
| Auth OIDC | `/auth` | `/auth/oidc`, `/auth/callback`, `/auth/config`, `/auth/local-login` |
| Profil & workspaces | `/me` | `/me`, `/me/workspaces`, `/me/git-credentials` |
| Cycle de vie workspace | `/me` | `/me/workspaces/{n}/up|stop|delete|recreate|status|logs` |
| Sessions | `/me` | `/me/workspaces/{n}/sessions`, WS `/me/workspaces/{n}/ssh` |
| Skills | `/me` | `/me/skills/search|audit|grants`, `/me/workspaces/{n}/skills` |
| VM de test | `/me` | `/me/workspaces/{n}/test-hosts|test-vm|.../shares|.../stacks` |
| Messages agents | `/me` | `/me/agent-messages`, `.../deliver`, `.../cancel` |
| Coffre & secrets | `/vault`, `/me` | `/vault/status|pin|keys`, `/me/secrets` |
| Compose | `/api/compose` | `/api/compose/deployments`, `.../nodes` |
| Applications (kiosque) | `/applications` | `/applications` |
| Événements | `/schemas` | `/schemas`, `/schemas/{code}/versions/{n}` |
| Administration | `/admin` | `/admin/hosts`, `/admin/hypervisors`, `/admin/oidc`, … |
| OAuth (clients MCP) | `/oauth`, `/.well-known` | `/oauth/authorize`, `/oauth/token` |

### Endpoints utilisateur clés

**Workspaces**
- `GET /me/workspaces` · `POST /me/workspaces` (201) · `DELETE /me/workspaces/{name}`
- `POST /me/workspaces/{name}/up` (202) · `.../stop` · `.../delete` · `.../recreate` (202)
- `GET .../status` · `GET .../logs` · `GET .../start-recipes` · `GET .../initializers` · `POST .../initializers/{id}/run`

**Sessions**
- `GET /me/workspaces/{name}/sessions` · `POST .../sessions` (201) · `DELETE .../sessions/{session}` (204)
- `WEBSOCKET /me/workspaces/{name}/ssh?session=<nom>`

**Skills**
- `GET /me/skills/search` · `GET /me/skills/audit` · `GET|POST /me/skills/grants`
- `GET .../grants/{id}/skillmd` · `POST .../grants/{id}/{approve|revoke|pause|resume}`
- `GET|POST /me/workspaces/{name}/skills` · `DELETE .../skills/{placement_id}` (204)

**VM de test**
- `GET /me/test-hypervisors` · `GET /me/workspaces/{ws}/test-hosts`
- `POST .../test-vm` · `DELETE .../test-vm/{host}` (204) · `POST .../test-vm/{host}/resolve-ip`
- `GET .../test-hosts/{host}/stacks` · `GET|PUT .../shares` · `GET|PUT .../links` · `DELETE .../links/{key}`

**Messages agents**
- `GET /me/agent-messages` · `GET .../pending-counts` · `GET .../{id}` · `POST .../{id}/deliver` · `POST .../{id}/cancel`

**Coffre**
- `GET /vault/status` · `POST /vault/pin/{setup|unlock|recover}` · `GET|POST /vault/keys`

## Outils MCP `devpod`

Registre : `backend/src/portal/mcp/devpod_tools/registry.py` (chaque outil porte
`description`, `inputSchema`, `scope`). **Scopes** : `read`, `write`, `exec`,
`admin`.

### Workspace
| Outil | Scope | Usage |
|-------|-------|-------|
| `workspace_list` / `workspace_get` / `workspace_status` | read | inventaire, état |
| `workspace_logs` / `workspace_resources` | read | logs, ressources |
| `workspace_tree` / `workspace_read_file` | read | arborescence, lecture fichier |
| `workspace_git_status` | read | état git |
| `workspace_git_commit` / `workspace_write_file` / `workspace_mkdir` | write | écritures |
| `workspace_secrets_list` (read) / `workspace_secrets_bind` (write) | read/write | secrets du workspace |
| `workspace_exec` / `workspace_reconnect` / `workspace_stop` / `workspace_restart` | exec | exécution / cycle de vie |
| `workspace_create` / `workspace_delete` / `workspace_apply_recipe` / `workspace_profile_set` | admin | provisioning |

### Session
`session_open` · `session_send` · `session_interrupt` · `session_close` ·
`session_capture` · `session_list` · `session_get` — pilotage d'un shell tmux
(ouvrir/envoyer/interrompre/capturer).

### Compose (services sur un hôte)
`compose_template_list|get` (read) · `compose_template_create|update` (admin) ·
`compose_service_list|status|logs` (read) · `compose_service_start|stop|restart|down` (exec).

### Skills
`skills_search` (read) · `skills_request_approval` (write, → grant pending) ·
`skills_place` / `skills_remove` (write) · `skills_pause` (write).
> Pas d'`approve`/`resume`/`revoke` en MCP : la **validation est humaine**.

### Messages, logs, plateforme
`message_send` (write) · `message_status` / `message_list` (read) · `logs_query`
(read) · `node_list` (read) · `operations_get|list` (read) · `portal_reload` (admin).

## Événements

Catalogue exposé sur `GET /schemas` (CloudEvents, `revision` + `events[]`), et
`GET /schemas/{eventCode}/versions/{n}` pour le `dataSchema` d'un type. Registre
fermé — types connus : `workspace.created|deleted|stopped|restarted`,
`session.created|closed`, `test_server.created|deleted`,
`compose_service.started|stopped`, `skill.available`.
