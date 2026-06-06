# M7 — Registre de recettes (devcontainer Features)

**Objectif :** permettre de personnaliser un workspace par des « recettes » composables qui
installent des outils dans le conteneur (claude-code, codex, gemini-cli, aider, goose, opencode,
cursor-agent…), en réutilisant le **standard devcontainer Features** pour rester portable. Registre
**propre au portail** (aucun couplage à ag.flow.docker), mais format identique pour copier librement.

## Modèle
- Une recette = une **Feature** : dossier avec `devcontainer-feature.json` (id, version, options,
  `installsAfter`) + `install.sh`.
- L'IHM compose les recettes choisies dans la clé `features` du `devcontainer.json` généré (M3.4).
- Deux scopes : `recipes/` (admin, partagé) et `users/<login>/recipes/` (perso). Résolution : perso
  écrase partagé à id égal.

## Étapes

### M7.1 — Schéma recette (`recipes/models.py`)
- Modèle pydantic du `devcontainer-feature.json` + un manifeste portail additionnel :
  ```yaml
  # recipe.meta.yaml (à côté de la Feature)
  id: "claude-code"
  version: "1.0.0"
  description: "Claude Code CLI"
  options:
    version: { type: string, default: "latest" }
  requires_secrets: ["llm/anthropic_key"]   # chemins RELATIFS au namespace user
  installs_after: ["base-tooling", "node"]
  ```
- `requires_secrets` : le portail résout ces secrets (scope user) et les injecte **au runtime**
  (`remoteEnv`/`containerEnv`), JAMAIS en build arg. Piège §D-21.

### M7.2 — Registre (`recipes/registry.py`)
- Chargement des recettes partagées + perso ; validation ; détection des cycles dans `installs_after`.
- `resolve_order(selected)` : tri topologique → ordre d'installation déterministe.

### M7.3 — Génération du devcontainer (compléter M3.4)
- À partir de `template` + `recipes[]` :
  - injecter les Features dans `features` (avec leurs options),
  - calculer l'ordre via `installs_after`,
  - collecter les `requires_secrets`, les résoudre (scope user), les ajouter en env runtime,
  - écrire le `devcontainer.json` effectif dans un fichier temporaire du dossier user.
- **Validation** : pas de Feature inconnue, options conformes, aucun secret en build arg.

### M7.4 — Premier lot de recettes
- Extraire (copier) depuis les 7 Dockerfiles existants → une Feature chacun :
  claude-code, gemini-cli, codex, aider, goose, opencode, cursor-agent.
- Chaque `install.sh` installe le **binaire/CLI** uniquement ; l'auth (clé) vient de `requires_secrets`
  au runtime. **Vérifier la commande d'installation actuelle de chaque CLI** (elles changent) plutôt
  que recopier une commande potentiellement périmée — lancer l'install dans un conteneur de test.
- Note : « cursor »/« codex » désignent ici leurs **CLI/agents**, pas les éditeurs desktop (inutiles
  dans un VS Code-in-browser). Cf. décision archi.

### M7.5 — Endpoints
- `GET /recipes` (partagées + perso visibles par le user).
- `POST/DELETE /me/recipes` (gérer ses recettes perso).
- `GET/POST/DELETE /admin/recipes` (partagées, require_admin).

## Tests
- Tri topologique : ordre correct ; cycle détecté → erreur claire.
- Génération : un workspace avec `recipes:[claude-code, aider]` produit un `devcontainer.json` avec
  les bonnes Features, dans le bon ordre, secrets en runtime (pas en build arg — assert sur le JSON).
- Override perso > partagé à id égal.
- (Intégration) : un `up` avec une recette installe bien le CLI dans le conteneur.

## Definition of Done
- DoD commune + tests verts + au moins claude-code installé et fonctionnel dans un workspace réel
  (auth via secret résolu, pas en clair).

## Pièges spécifiques M7
- §D-21 (secrets runtime, jamais build arg — le piège le plus probable ici), validation des Features
  inconnues, cycles `installs_after`.
- Piège install : ne pas figer une commande d'install de CLI sans la tester (elles évoluent vite).
  Tester chaque `install.sh` dans un conteneur jetable avant de committer la recette.
- Piège portabilité : ne RIEN mettre de spécifique au portail dans une Feature (pas de chemin `/data`,
  pas de référence au portail) → l'artefact reste copiable vers ag.flow.docker et inversement.
