# M1 — Fondations : config + résolveur de secrets

**Objectif :** squelette du projet, modèles pydantic des deux configs, chargement/écriture atomique,
et le résolveur de secrets avec ses deux backends. Aucune dépendance réseau. C'est la base testable
de tout le reste.

## Prérequis
- `pyproject.toml` (uv ou poetry), dépendances : `pydantic>=2`, `pydantic-settings`, `pyyaml`,
  `pytest`, `pytest-asyncio`, `ruff`, `mypy`.

## Étapes

### M1.1 — Squelette
- Créer l'arbo `src/portal/...` (voir `04_CLAUDE.md`).
- Configurer `ruff` + `mypy` (strict) dans `pyproject.toml`.

### M1.2 — Modèles config (`config/models.py`)
- `GlobalConfig`, `UserConfig` et sous-modèles selon `02_CONFIG_REFERENCE.md`.
- `extra="forbid"` partout.
- Validators :
  - `WorkspaceSpec.name` : regex `^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$`.
  - `secret_ns` : format UUID.
  - `host`/`git_credential` référencés : validés au **chargement combiné** (fonction
    `load_user_config(login, global_cfg)` qui croise les deux), pas dans le modèle isolé.

### M1.3 — Chargement / écriture (`config/store.py`)
- `load_global() -> GlobalConfig`, `load_user(login) -> UserConfig`.
- `save_user(login, cfg)` : sérialise YAML → écriture **atomique** (tempfile même dossier +
  `os.replace`). Voir piège §G-34.
- `ensure_user_dir(login)` : crée `users/<login>/{keys/git,keys/workspaces,recipes,templates,devpod}`,
  perms 700 sur le dossier user, 600 sur les fichiers sensibles.
- **Toute construction de chemin** passe par un helper `safe_user_path(login, *parts)` qui valide
  (regex login, pas de `..`, `is_relative_to`). Piège §C-18.

### M1.4 — Résolveur de secrets (`secrets/`)
- Type `Secret` : wrapper string avec `__repr__ = "Secret(***)"` et `__str__` idem ; valeur réelle
  accessible via `.reveal()` uniquement. Piège §D-23.
- `backends/inline.py` : lit `users/<login>/secrets.yaml` (scope user) ou la section globale.
- `backends/harpocrate.py` : client `httpx` vers Harpocrate (GET secret par path). API key globale ou
  perso (champ `harpocrate.api_key` du user, sinon globale).
- `resolver.py` : implémente `resolve(value, scope)` selon le contrat de `02` §Contrat.
  - Scope = `Scope(kind="user"|"global", secret_ns=..., login=...)`.
  - **Rejets** (lever `SecretAccessError`) : path user commençant par `/`, contenant `..`, ou un
    autre GUID. Tester chacun. Pièges §D-22.
  - Si `backend=harpocrate` mais `api_key` vide → fallback inline (log un warning, une seule fois).

## Tests (obligatoires)
- Parsing d'un YAML valide (global + user) ; rejet d'un champ inconnu (`extra=forbid`).
- `name` invalides rejetés : `Ab`, `a..b`, `../x`, `a_b`, chaîne de 40 chars.
- Résolveur : littéral inchangé ; `${env://X}` ok et erreur si absent ; `${vault://git/x}` user →
  préfixe `devpod/<ns>/git/x` ; rejets §D-22 ; fallback inline si clé Harpocrate vide.
- `Secret` ne fuit pas en repr/log (assert sur `repr()` et sur un format de log).
- Écriture atomique : simuler un crash (écrire dans temp, ne pas replace) ne corrompt pas l'existant.

## Definition of Done
- DoD commune (`04`) + tous les tests ci-dessus verts.
- `safe_user_path` couvre 100% des constructions de chemin user du module.

## Pièges spécifiques M1
- §C-18 (path traversal), §D-22/23 (isolation + non-fuite secrets), §G-34 (écriture atomique).
- Piège pydantic : un `${vault://...}` est une **string** dans le modèle ; la résolution se fait
  APRÈS chargement, pas dans un validator (sinon on stocke le secret résolu en mémoire/dump).
