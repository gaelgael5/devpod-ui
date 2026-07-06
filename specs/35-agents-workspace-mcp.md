# Spec 35 — Accès MCP direct des agents workspace

> Statut : backend implémenté (migration 056), UI en cours — 2026-07-06
> Repo : devpod-ui
>
> Écart d'implémentation notable : les hosts **docker-tls** n'exposent aucun accès
> filesystem (seul le daemon mTLS :2376 est joignable) — la dépose des fichiers
> agent-config est donc **SSH uniquement en v1**. Un workspace demandant des agents
> sur un host docker-tls est rejeté en 422 au provisioning ; le resync à chaud les
> saute (skipped) avec log. Canal envisagé pour la v2 : conteneur éphémère via
> l'API Docker (put_archive) — cf. §10.
>
> Décisions de design (session 2026-07-06) : clef API **par workspace × profil exposé**
> (jamais de clef partagée) ; fichiers de paramétrage générés **sur le host** de chaque nœud
> et montés dans le conteneur (régénération à chaud sans reprovisionner) ; types d'agents en
> table avec **template Jinja + nom de fichier** ; l'utilisateur choisit ses agents à la
> création du workspace. Référence de workspace = ws_id texte `{login}-{name}` (convention
> spec 34, pas de FK dure).

## 1. Contexte et objectif

Aujourd'hui les agents Claude tournant dans les workspaces n'accèdent aux fonctions devpod
qu'indirectement, via le Claude connecté à claude.ai (gateway MCP côté cloud). Cette spec
donne aux agents **locaux** (Claude Code, Gemini CLI, Codex…) un accès direct à la gateway
MCP du portail : le portail génère dans chaque workspace les fichiers de configuration MCP
attendus par chaque type d'agent, avec des clefs API dédiées.

Principes directeurs :

- **Une clef par workspace × profil** : l'audit log attribue chaque appel au bon workspace,
  la révocation est chirurgicale, la rotation est gratuite (à chaque `up`).
- **Le profil MCP reste le point de contrôle** : seuls les profils cochés
  « exposé aux workspaces » sont injectés. Décocher = révocation immédiate (fail closed).
- **Fichiers sur le host, montés dans le conteneur** : le portail peut régénérer la config
  à chaud (changement de profil, rotation) sans toucher au conteneur.
- **Types d'agents déclaratifs** : ajouter un agent = une ligne en table (template Jinja +
  nom de fichier + chemin cible), zéro code de provisioning.

## 2. Modèle de données (migration 056)

### 2.1 `mcp_profile` — nouvelle colonne

| Colonne                 | Type      | Contraintes                  |
|-------------------------|-----------|------------------------------|
| `exposed_in_workspaces` | `boolean` | `NOT NULL DEFAULT false`     |

### 2.2 Nouvelle table `agent_type`

| Colonne       | Type          | Contraintes                                              |
|---------------|---------------|----------------------------------------------------------|
| `id`          | `text`        | PK, slug `^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$`          |
| `label`       | `text`        | `NOT NULL` (nom affiché, ex. « Claude Code »)            |
| `filename`    | `text`        | `NOT NULL` (nom du fichier généré, ex. `.mcp.json`) — nom simple, pas de `/` ni `..` (CHECK applicatif pydantic) |
| `template`    | `text`        | `NOT NULL` (template Jinja du contenu)                   |
| `target_path` | `text`        | `NOT NULL` (chemin cible dans le conteneur où le fichier doit apparaître, templatable : `{{ project_root }}/.mcp.json`, `{{ home }}/.gemini/settings.json`) |
| `enabled`     | `boolean`     | `NOT NULL DEFAULT true`                                  |
| `created_at`, `updated_at` | `timestamptz` | `NOT NULL DEFAULT now()`                    |

Seed : une ligne `claude` (template `mcpServers` JSON + `target_path`
`{{ project_root }}/.mcp.json`). Les autres agents seront ajoutés par l'admin via l'UI.

### 2.3 `mcp_apikey` — nouvelles colonnes

| Colonne         | Type   | Contraintes                                             |
|-----------------|--------|----------------------------------------------------------|
| `workspace_ref` | `text` | `NULL` (ws_id `{login}-{name}` pour les clefs workspace) |

Une clef workspace se reconnaît à `workspace_ref IS NOT NULL`. Elle porte toujours un
`profile_id` (jamais de clef workspace sans profil — deny-by-default conservé).

Index : `idx_mcp_apikey_workspace_ref` sur `(workspace_ref) WHERE workspace_ref IS NOT NULL`.

## 3. Cycle de vie des clefs

| Événement | Effet |
|---|---|
| `up` du workspace | Pour chaque profil du propriétaire avec `exposed_in_workspaces` : révoque l'ancienne clef `(ws, profil)` si présente, en crée une neuve (rotation systématique). Label `ws:{ws_id}/{profil}`. |
| `delete` du workspace | Révocation de toutes les clefs `workspace_ref = ws_id` + purge de l'arborescence host. |
| Décochage `exposed_in_workspaces` | **Fail closed immédiat** : révocation de toutes les clefs workspace du profil + régénération des fichiers sur tous les hosts concernés (entrée serveur retirée). |
| Cochage `exposed_in_workspaces` | Régénération : création des clefs manquantes pour les workspaces existants dont le spec demande des agents + push des fichiers. |
| Édition d'un `agent_type` (template/filename) | Régénération des fichiers sur tous les hosts concernés. |

Les clefs workspace apparaissent dans l'UI MCPApikeys avec un badge « workspace » ;
elles ne sont pas éditables à la main (révocation seule).

## 4. Génération des fichiers

### 4.1 Renderer

- Jinja2 **`SandboxedEnvironment`** obligatoire : les templates sont saisis par l'admin et
  rendus avec des secrets en contexte — pas d'accès aux attributs Python
  (`{{ ''.__class__ }}` doit lever, testé).
- `autoescape=False` (on génère du JSON/TOML, pas du HTML) ; le template appelle
  `| tojson` lui-même là où il faut.
- Contexte de rendu :

```python
{
  "servers": [  # un élément par profil exposé
    {"name": "<slug-profil>", "url": "<external_url>/mcp/", "token": "mcpk_..."}
  ],
  "workspace": {"id": ws_id, "name": name, "owner": login},
  "home": "/home/vscode",          # remoteUser du devcontainer
  "project_root": "/workspaces/<name>",
}
```

Exemple de template seed `claude` :

```jinja
{"mcpServers": {
  {%- for s in servers %}
  {{ s.name | tojson }}: {"type": "http", "url": {{ s.url | tojson }},
    "headers": {"Authorization": {{ ("Bearer " ~ s.token) | tojson }}}}{{ "," if not loop.last }}
  {%- endfor %}
}}
```

### 4.2 Arborescence sur le host

```
~/.devpod-portal/agent-config/          # 700, à côté du .devpod-portal-dc existant
└── {ws_id}/                            # 700
    └── {agent_id}/                     # 700
        └── {filename}                  # 600
```

- `ws_id` et `agent_id` sont déjà validés par regex stricte (pas de traversal), mais le
  constructeur de chemin revérifie (`is_relative_to` sur la racine côté portail avant tar).
- Push par le canal SSH existant (tar streamé, comme `_upload_devcontainer_to_ssh`),
  écriture atomique côté host (extraction dans un tmpdir + `mv`), purge au delete.
- Regroupement par host : la régénération d'un profil rassemble les workspaces impactés
  par nœud et pousse une archive par nœud.

### 4.3 Montage et placement dans le conteneur

- `devcontainer.json` : `mounts` += bind **du répertoire**
  `~/.devpod-portal/agent-config/{ws_id}` → `/opt/agent-config`, **read-only**.
  Monter le répertoire (jamais les fichiers un à un) : le remplacement atomique côté host
  change l'inode, un bind de fichier resterait figé sur l'ancien inode — le bind de
  répertoire voit la nouvelle version. C'est ce qui rend la régénération à chaud possible.
- `postCreateCommand` += pour chaque agent du spec : symlink
  `{target_path}` → `/opt/agent-config/{agent_id}/{filename}`. Le symlink pointe un chemin,
  pas un inode : les mises à jour à chaud sont visibles sans re-run.
- Si `target_path` tombe sous `project_root` (cas Claude `.mcp.json`) : ajout du nom dans
  `.git/info/exclude` du clone (le repo de l'utilisateur reste propre, on ne touche pas au
  `.gitignore` versionné).

## 5. Spec workspace et API

### 5.1 `WorkspaceSpec`

Nouveau champ `agents: list[str] = []` — validé par la regex slug (field_validator, comme
`recipes`) puis contre la table `agent_type` au provisioning (agent inconnu ou `enabled=false`
= 400 explicite, pas d'ignorance silencieuse).

### 5.2 Routes

| Route | Rôle |
|---|---|
| `GET/POST /admin/agent-types`, `GET/PATCH/DELETE /admin/agent-types/{id}` | CRUD admin. DELETE refuse si un workspace référence l'agent. |
| `POST /admin/agent-types/{id}/preview` | Rendu du template avec un contexte factice (tokens `mcpk_XXXX…`) pour l'éditeur UI. |
| `PATCH /me/mcp/profiles/{id}` | Accepte `exposed_in_workspaces` ; le décochage déclenche révocation + régénération (§3). |
| `GET /me/agent-types` | Liste (id, label) pour le formulaire de création de workspace. |

## 6. UI

- **MCPProfiles** : case à cocher « Exposé aux workspaces » par profil, avec confirmation au
  décochage (« révoque N clefs actives »).
- **Admin → Types d'agents** : table CRUD, éditeur de template (textarea monospace) +
  bouton « Prévisualiser » (route preview).
- **Création/édition de workspace** : sélection multiple des agents (liste des
  `agent_type` enabled).
- **MCPApikeys** : badge « workspace » + `workspace_ref` visible, action révoquer seule.
- i18n fr/en, tests Vitest sur chaque composant modifié.

## 7. Sécurité

- Tokens en clair uniquement : (a) dans les fichiers 600 sur des hosts admin-only,
  (b) dans le conteneur du workspace (modèle assumé de tous les clients MCP). Jamais en log,
  jamais dans une réponse API après création, jamais dans le repo git de l'utilisateur.
- Rotation à chaque `up`, révocation au delete et au décochage — fenêtre d'exposition courte.
- Sandbox Jinja : test de non-régression avec template hostile.
- La gateway continue de filtrer par profil côté serveur : même un fichier trafiqué dans le
  conteneur ne donne que ce que le profil de la clef autorise.
- Aucun changement au modèle d'auth de la gateway (`BearerGate` inchangé) ; l'URL utilisée
  est l'`external_url` publique (les nœuds ne voient pas le réseau Docker du portail).

## 8. Tests obligatoires (TDD)

1. **Migration 056** : up sur base peuplée, colonnes/table/seed présents.
2. **Renderer** : rendu claude nominal (JSON valide, N profils) ; template hostile
   `{{ ''.__class__.__mro__ }}` → erreur propre ; `filename` avec `/` ou `..` rejeté.
3. **Clefs** : rotation au `up` (ancienne révoquée, nouvelle valide) ; delete → toutes
   révoquées ; décochage profil → révoquées + fichier régénéré sans l'entrée ; clef
   workspace refusée sur un profil d'un autre user.
4. **Chemins** : construction de l'arborescence refuse tout ws_id/agent_id hors regex.
5. **Provisioning** : `devcontainer.json` généré contient le mount ro ; `postCreateCommand`
   contient les symlinks et l'entrée `.git/info/exclude` pour un target sous project_root.
6. **Routes** : CRUD admin (403 pour dev), preview, PATCH profil déclenche la révocation,
   validation `agents` inconnus → 400.
7. **Frontend** : Vitest sur MCPProfiles (coche + confirmation), formulaire workspace
   (sélection agents), page admin agent-types.

## 9. Découpage en tâches (ordre d'exécution)

1. Migration 056 + modèles pydantic (`agent_type`, colonnes) — tests 1.
2. Service clefs workspace (create/rotate/revoke par ws×profil) — tests 3 (partie service).
3. Renderer Jinja sandboxé + constructeur d'arborescence locale — tests 2, 4.
4. Push SSH par host (réutilisation du canal tar) + purge — test manuel test1 + unitaires
   sur la construction d'archive.
5. Intégration provisioning : champ `agents`, mount, postCreate, appels au `up`/`delete` —
   tests 5, hooks de cycle de vie.
6. Routes API + déclencheurs (PATCH profil, CRUD agent-types) — tests 6.
7. UI (profils, admin agent-types, formulaire workspace, apikeys) — tests 7.
8. Vérification bout en bout sur test1 (TESTER-MON-DEV.md) : créer un workspace avec
   `agents=[claude]`, vérifier le fichier monté, lancer Claude Code dedans, appeler un outil
   `devpod__*`, vérifier l'audit log ; décocher le profil et vérifier le fail closed à chaud.

## 10. Hors périmètre v1

- Renderer TOML Codex (le support HTTP streamable de Codex sera vérifié contre la version
  réellement installée le jour où on l'ajoute — simple ligne en table si le format suit).
- Installation automatique des CLI agents dans l'image (relève des recettes existantes).
- Clefs par (user × profil) partagées entre workspaces (écartée : audit et révocation).
