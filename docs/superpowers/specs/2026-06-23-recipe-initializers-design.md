# Recipe initializers — design

**Date** : 2026-06-23
**Statut** : validé (brainstorming), prêt à implémenter

## Problème

Après l'installation d'un outil dans un workspace (ex. Claude Code), l'utilisateur a
besoin d'appliquer une configuration : copier des fichiers, modifier des nœuds précis
d'un fichier JSON de config (ex. forcer `permissions.defaultMode = bypassPermissions`
dans `~/.claude/settings.json`).

Contraintes découvertes :

- **Ce n'est pas faisable à l'install de la feature devcontainer** : les features
  s'exécutent au *build* de l'image, quand le memory-volume `.claude` n'est **pas**
  monté. Tout écrit dans `/home/vscode/.claude` à ce moment part dans la couche image
  puis est masqué par le volume au runtime.
- **Ce n'est pas faisable dans un `start.sh`** : il tourne à chaque démarrage, donc
  réécrase à chaque fois les ajustements faits entre-temps par l'utilisateur.

## Décision

Un nouveau type de recipe, **`type: initialize`**, déclaratif et **déclenché
manuellement** par l'utilisateur depuis l'UI, au moment où *lui* sait que c'est
pertinent. Un **moteur centralisé** dans le portail applique les opérations dans le
conteneur, au runtime (volume monté), gardé par une **sentinelle** qui garantit
« une seule fois ».

C'est « factorisable » : l'auteur de recipe écrit uniquement du YAML déclaratif ; le
moteur d'exécution est unique, écrit et testé une fois, réutilisé par toutes les
recipes `initialize`.

## Modèle de données

### Nouveau type de recipe

`RecipeMeta.type` (pydantic `Literal`) gagne la valeur `"initialize"`, à côté de
`install`/`start`. Une recipe `initialize` :

- ne porte **ni** `devcontainer-feature.json` **ni** `start.sh` ;
- déclare ses opérations dans `recipe.meta.yaml` via deux nouvelles sections
  optionnelles : `copy` et `transform` ;
- peut embarquer un dossier `files/` (sources de `copy`), copié dans le répertoire de
  la recipe comme les autres fichiers (`sync.py`).

### Schéma des opérations (nouveaux modèles pydantic, `extra="forbid"`)

```yaml
copy:
  - source: files/claude            # relatif au dossier de la recipe
    target: /home/vscode/.claude    # absolu dans le conteneur

transform:
  - op: replace                     # remplace (ou crée) le nœud cible
    target:
      file: /home/vscode/.claude/settings.json
      node: $.permissions
    value:                          # valeur inline (JSON/YAML)
      allow: []
      defaultMode: bypassPermissions
  - op: remove                      # supprime le nœud cible (pas de value)
    target:
      file: /home/vscode/.claude/settings.json
      node: $.foo.bar
```

- **`copy[]`** : `{source, target}`. `source` relatif au dossier de la recipe (pas de
  `..`, pas de chemin absolu). `target` absolu dans le conteneur.
- **`transform[]`** : `{op: replace|remove, target: {file, node}, value?}`.
  - `op: replace` exige `value`, `op: remove` interdit `value`.
  - `target.file` : chemin absolu d'un fichier **JSON** dans le conteneur.
  - `target.node` : **dot-path** (sous-ensemble de JSONPath) : `$.permissions`,
    `$.a.b.c`. Pas de wildcard ni de filtre (YAGNI).

### Recipe d'exemple : `claude-bypass-permissions`

```yaml
id: claude-bypass-permissions
key: <uuid>
type: initialize
version: "1.0.0"
description: "Aligne les permissions Claude Code sur bypassPermissions"
transform:
  - op: replace
    target:
      file: /home/vscode/.claude/settings.json
      node: $.permissions
    value:
      allow: []
      defaultMode: bypassPermissions
```

## Moteur & exécution

### Moteur (centralisé, Python 3 / stdlib)

Un script unique livré avec le portail (asset backend), jamais dupliqué dans les
recipes. Reçoit les opérations sérialisées en JSON (sur stdin) et, dans le conteneur :

1. Calcule l'emplacement de la **sentinelle** (voir plus bas). Si elle existe et que
   `force` est faux → s'arrête avec un statut « déjà appliqué » (exit code dédié).
2. Applique `copy` : copie récursive `source → target` (crée les dossiers parents).
3. Applique `transform` : pour chaque op, charge le JSON cible (le crée `{}` s'il
   n'existe pas), résout le dot-path, fait `replace`/`remove`, puis **réécrit
   atomiquement** (tempfile dans le même dossier + `os.replace`, `indent=2`).
   - `remove` sur un nœud / fichier absent = no-op (idempotent).
4. Crée la sentinelle.

Langage : **Python 3 / stdlib** (`json`, `pathlib`, `shutil`, `os`, `sys`). Hypothèse :
`python3` présent dans le conteneur (vrai pour l'image de base devcontainers Ubuntu).
Si absent, le moteur échoue avec un message clair dans le log (fail-closed, **pas** de
`apt-get` silencieux).

### Sentinelle

Fichier-témoin vide, nom `{id}@{version}`, posé dans un sous-dossier `.portal/` du
**répertoire de la première cible** déclarée par la recipe :

- `copy` présent → `dirname` traité depuis `copy[0].target` (qui est un dossier) ;
- sinon → `dirname(transform[0].target.file)`.

Pour `claude-bypass-permissions` : `/home/vscode/.claude/.portal/claude-bypass-permissions@1.0.0`.
La cible étant dans le volume persistant `.claude`, la sentinelle l'est aussi → « une
seule fois » survit aux rebuilds. Bumper la `version` change le nom du témoin → l'action
peut se rejouer une fois (canal de mise à jour volontaire).

### Canal d'exécution

Réutilise le transport des recipes `start` (`workspace_ssh.py`) : commande SSH via
`ProxyCommand devpod ssh --stdio <ws_id>`, identité dédiée. Différence : exécution
**non-interactive** (pas de PTY ni WebSocket — l'action est courte), `stdout`/`stderr`
capturés. Le moteur et les ops sont transmis encodés base64 ; le moteur lit les ops sur
stdin. Un helper de construction de commande SSH est extrait pour être partagé entre le
terminal interactif et l'exécution non-interactive.

## API backend

- **`GET /me/workspaces/{name}/initializers`** → `[{id, description, version}]` : les
  recipes `type: initialize` rattachées au workspace. Modelé sur `get_workspace_start_recipes`.
  Pas d'état temps-réel « déjà appliqué » en v1 (éviterait une lecture SSH par
  affichage) — l'état se révèle au lancement.
- **`POST /me/workspaces/{name}/initializers/{id}/run`** (query `force: bool = false`)
  → exécute le moteur dans le conteneur, retourne `{applied: bool, already_applied: bool, log: str}`.
  Exige un workspace **démarré** (sinon 409/erreur explicite).

`WorkspaceSpec` gagne un champ `init_recipes: list[str]` (validation d'ID identique à
`start_recipes`), qui liste les actions `initialize` du workspace.

## UI (frontend)

Composant partagé **`InitializersMenu`**, monté à deux endroits :

- **`WorkspaceCard`** : dans la zone d'actions du workspace.
- **`WorkspaceTerminals`** (gestion des sessions) : dans le header.

Comportement :

- Liste les actions (`useWorkspaceInitializers`, TanStack Query).
- Bouton **« Lancer »** par action → `POST …/run` (`useRunInitializer`) → **toast** de
  résultat (« Appliqué » / « Déjà appliqué » / erreur), accès au **log** détaillé.
- Option secondaire (menu ⋯) **« Forcer la réapplication »** → `run` avec `force=true`.
- Bouton désactivé si le workspace n'est pas démarré.

i18n : nouvelles clés sous `workspaces.initializers.*` (fr + en).

## Découpage

- **Lot A — backend cœur** : `type: initialize` + modèles `copy`/`transform`, moteur
  Python + helper SSH non-interactif, sentinelle, champ `init_recipes`, les 2 endpoints,
  et la recipe d'exemple `claude-bypass-permissions`. Vérifiable en curl/CLI.
- **Lot B — UI** : `InitializersMenu` + hooks + intégrations `WorkspaceCard` et
  `WorkspaceTerminals` + i18n.

Commit entre les deux lots.

## Tests (TDD)

**Lot A :**
- Modèles : parsing YAML valide (copy/transform), rejets (`replace` sans `value`,
  `remove` avec `value`, `node` invalide, `source` absolu/`..`, `target.file` relatif).
- Type `initialize` : chargé par le registry, ignoré comme feature au build devcontainer.
- Moteur (testé en pur Python, hors conteneur) : replace crée/écrase un nœud profond ;
  remove est idempotent ; fichier cible absent → créé ; écriture atomique ; sentinelle
  posée puis court-circuit ; `force` ignore la sentinelle ; dot-path invalide rejeté.
- Endpoints : liste filtrée par `init_recipes` ; run sur workspace arrêté → erreur ;
  `force` propagé.

**Lot B :**
- `InitializersMenu` : rend la liste, désactive si arrêté, déclenche `run`, affiche les
  toasts succès/déjà-appliqué/erreur (Vitest + RTL).
