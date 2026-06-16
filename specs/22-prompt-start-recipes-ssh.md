# Chantier — Sessions SSH persistantes + recettes de type `start`

> Dépôt **devpod-ui**. Deux fonctions **de base** du workspace : ouvrir une session SSH persistante,
> et y lancer un script de démarrage. Le script de démarrage est porté par les **recettes** : on
> ajoute un champ `type: install | start`. Les recettes `start` sont sélectionnables comme script
> lancé à l'ouverture d'une session SSH. UI : « Open » → « Open VSCode », + bouton « New SSH session ».
> **Hors périmètre (second temps)** : disponibilité des secrets/env dans la session SSH (ex.
> `ANTHROPIC_API_KEY` pour `claude --rc`). Chantier suivant.

## 0. Préalables

1. Lis `CLAUDE.md`, `LESSONS.md`. **Mime les patterns existants** :
   - recettes : `recipes/models.py` (`RecipeMeta`), `recipes/registry.py`, `16_M7_recipes.md` ;
   - sessions SSH : `routes/ssh_proxy.py` (route websocket `/hosts/{name}/ssh`, validation origin +
     auth + bridge PTY) et le frontend `SshTerminalWindow` ;
   - workspaces : `config/models.py` (`WorkspaceSpec`), `devpod/service.py`, `routes/workspace_ops.py`,
     frontend `@/features/workspaces` (carte, bouton « Open », `WorkspaceCreate`) ;
   - fork user d'une recette/profil : chantier `19` (création user-scoped à la volée).
2. Branche `dev`. Commits conventionnels **FR**. Aucun fichier > 300 lignes. **Pas de DB.**
   Écritures YAML **atomiques**.
3. **`tmux` doit être garanti dans le base** (image/devcontainer de base), pas via une recette : la
   persistance est une fonction de base, elle ne doit dépendre d'aucune recette sélectionnée.

## 1. Modèle de recette — champ `type`

Ajouter à `RecipeMeta` :

```python
type: Literal["install", "start"] = "install"   # défaut = install → rétrocompat, rien à migrer
```

- **`install`** (existant) : Feature devcontainer — `recipe.meta.yaml` + `devcontainer-feature.json`
  + `install.sh`. Inchangé. `installs_after`, `options` restent valides.
- **`start`** : `recipe.meta.yaml` (avec `type: start`) + **`start.sh`**. **Pas** de
  `devcontainer-feature.json` ; `installs_after` ignoré.

Validation (registre) :
- une recette `start` **doit** avoir `start.sh` et **ne doit pas** avoir de `devcontainer-feature.json` ;
- une recette `install` garde l'exigence actuelle ;
- `RecipeRegistry` expose un filtre par type : `list_recipes(scope, type="start")`.

Exemple `recipes/claude-rc/` :
```yaml
# recipe.meta.yaml
id: claude-rc
type: start
version: 1.0.0
description: "Lance Claude Code en remote-control (pilotable depuis le mobile)"
```
```bash
# start.sh
#!/usr/bin/env bash
set -euo pipefail
exec claude --rc        # cf. claude --help selon la version (rc | --remote-control)
```

## 2. Config workspace — recettes `start` attachées

Ajouter à `WorkspaceSpec` (à côté de `recipes: list[str]`, qui reste les recettes **install**) :

```python
start_recipes: list[str] = Field(default_factory=list)   # ids de recettes type=start
default_start: str = ""                                   # id par défaut du menu (optionnel)
```

Dans le paramétrage du workspace (frontend) : multi-sélection des recettes `start` disponibles
(partagées + user), avec possibilité de **créer une recette `start` user à la volée** (réutilise le
pattern de fork du chantier `19`) — pas de script « inline » stocké hors registre.

## 3. Backend — ouverture d'une session SSH persistante

Nouvelle route websocket, calquée sur `host_ssh_terminal`, mais ciblant un workspace :

```
@router.websocket("/workspaces/{name}/ssh")     # query: ?start=<recipe_id> (optionnel)
```
- Mêmes garde-fous que la route hosts : validation d'origin (anti-CSWSH), auth session, périmètre user.
- Résout `ws_id = <login>-<name>`. Le start recipe (si `?start=`) est lu depuis le registre
  (scope user puis partagé), son `start.sh` est encodé base64 (évite tout problème de quoting /
  injection d'argument).
- Commande exécutée :
  ```
  devpod ssh <ws_id> --command 'tmux new -A -s <session> -- bash -lc "$(echo <b64> | base64 -d)"'
  ```
  - `tmux new -A -s <session>` = attache-ou-crée → **persistance de base** : la déconnexion du
    websocket ne tue pas la session ; reconnexion = réattache.
  - `<session>` = l'id du start recipe, ou `main` pour un shell nu (`?start` absent → pas de `bash -lc`,
    juste `tmux new -A -s main`).
  - tmux n'exécute la commande qu'à la **création** ; sur réattache, le `start.sh` n'est pas relancé.
- Bridge PTY ↔ websocket : réutiliser la plomberie de `ssh_proxy.py`.

> `devpod ssh --command` : vérifier sur la version installée que la session ouvre bien dans le dossier
> projet (`devpod ssh --help`). Idem pour la forme exacte de `claude --rc` (cf. recette ci-dessus).

Optionnel : `GET /workspaces/{name}/start-recipes` renvoie les start recipes attachées (pour peupler
le menu du bouton).

## 4. Frontend (`@/features/workspaces`)

- Renommer le bouton **« Open »** → **« Open VSCode »** (inchangé fonctionnellement : ouvre l'URL openvscode).
- Ajouter **« New SSH session »** : un menu listant les `start_recipes` attachées + une entrée
  **« Shell »** (session nue). Chaque entrée ouvre `SshTerminalWindow` pointé sur
  `/workspaces/{name}/ssh?start=<id>` (ou sans `start` pour le shell).
- Exposer aussi la commande `devpod ssh <ws_id>` (copiable) pour un terminal natif.
- i18n `fr.json` / `en.json` pour tous les libellés.

## 5. Tests

- `RecipeMeta` : `type` défaut `install` ; une recette `start` sans `start.sh` → rejet ; une recette
  `start` avec `devcontainer-feature.json` → rejet ; `list_recipes(type="start")` filtre correctement.
- Registre : fork user d'une recette `start` (scope user écrase partagé à id égal).
- Route ws SSH : auth/origin appliqués comme la route hosts ; `?start` inconnu → erreur propre ;
  base64 du `start.sh` correct ; `?start` absent → `tmux new -A -s main`.
- Frontend : « Open VSCode » ouvre l'URL ; « New SSH session » liste les start recipes + Shell.

## Hors périmètre (second temps)

- **Secrets/env dans la session SSH** : faire en sorte que les `requires_secrets` (ex.
  `ANTHROPIC_API_KEY`) soient présents dans l'environnement des shells SSH interactifs, pour que
  `claude --rc` fonctionne. À traiter dans un chantier dédié (`remoteEnv` / fichier de profil sourcé).
- Survie des sessions à un `devpod stop` (tmux meurt avec le conteneur) : non couvert, par nature.
