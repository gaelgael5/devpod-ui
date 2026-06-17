# Inventaire des données persistées sur disque

> Généré le 2026-06-17 — tour complet du backend `portal`.

---

## 1. Configuration globale

| Champ | Valeur |
|-------|--------|
| Modèle | `GlobalConfig` |
| Chemin | `/data/config.yaml` |
| Fonction | `config/store.py :: save_global()` |
| Format | YAML |
| Écriture | Atomique : tempfile + `os.replace()` |

Contient : hosts, hyperviseurs, Caddy, cloudflare-manager, auth OIDC, secrets backends, devpod defaults.

---

## 2. Configuration utilisateur

| Champ | Valeur |
|-------|--------|
| Modèle | `UserConfig` (workspaces, git_credentials, defaults, secret_ns) |
| Chemin | `/data/users/{login}/config.yaml` |
| Fonction | `config/store.py :: save_user()`, `provision_user()` |
| Format | YAML |
| Écriture | Atomique : tempfile + `os.replace()` |

Login validé par regex. Tous les chemins passent par `safe_user_path()`.

---

## 3. Clés SSH — workspaces

| Champ | Valeur |
|-------|--------|
| Modèle | Paire Ed25519 (privée + publique) |
| Chemin | `/data/users/{login}/keys/workspaces/{workspace}/id_ed25519` + `.pub` |
| Fonction | `ssh_keys.py :: ensure_workspace_ssh_key()` |
| Format | PEM (privée `0o600`), OpenSSH (publique `0o644`) |
| Écriture | Atomique : tempfile + `os.replace()` |

---

## 4. Clés SSH — git credentials

| Champ | Valeur |
|-------|--------|
| Modèle | Paire Ed25519 |
| Chemin | `/data/users/{login}/keys/git/{cred_name}/id_ed25519` + `.pub` |
| Fonction | `ssh_keys.py :: generate_git_credential_ssh_key()` |
| Format | PEM (privée `0o600`), OpenSSH (publique `0o644`) |
| Écriture | Atomique : tempfile + `os.replace()` |

---

## 5. Clés SSH — hosts

| Champ | Valeur |
|-------|--------|
| Modèle | Paire Ed25519 |
| Chemin | `/data/keys/hosts/{host_name}_ed25519` |
| Fonction | `routes/admin.py :: generate_host_ssh_key()` |
| Format | PEM |
| Écriture | Directe |

---

## 6. Certificats X.509 — nœuds

| Champ | Valeur |
|-------|--------|
| Modèle | Certificat signé par la CA interne |
| Chemin | `/data/certs/nodes/{node_name}/server-cert.pem` |
| Fonction | `nodes/enroll.py :: _save_node_cert()` |
| Format | PEM |
| Écriture | Atomique : tempfile + `os.replace()` |

CA en lecture seule : `/data/certs/ca/{ca.pem,ca-key.pem}`.

---

## 7. Recipes partagées (admin)

| Champ | Valeur |
|-------|--------|
| Modèle | `RecipeMeta` + scripts |
| Chemin | `/data/recipes/{recipe_id}/recipe.meta.yaml` + `install.sh` + `devcontainer-feature.json` |
| Fonction | `routes/recipes.py :: admin_create_shared_recipe()`, `admin_update_shared_recipe()` |
| Format | YAML + Shell + JSON |
| Écriture | Atomique par fichier : tempfile + `os.replace()` ; création : mkdir(tmp) + rename |

Sync initial depuis le bundle embarqué : `recipes/sync.py :: sync_bundled_recipes()` (shutil.copytree + rename).
Champ `key` (UUID) obligatoire depuis M7. `installs_after` contient des GUIDs.

---

## 8. Recipes personnelles — start recipes

| Champ | Valeur |
|-------|--------|
| Modèle | `RecipeMeta` (type=start) + script |
| Chemin | `/data/users/{login}/recipes/{recipe_id}/recipe.meta.yaml` + `start.sh` |
| Fonction | `routes/recipes.py :: create_personal_start_recipe()` |
| Format | YAML + Shell (`start.sh` chmod `0o755`) |
| Écriture | mkdir(tmp) + write_text + rename |

---

## 9. Profiles

| Champ | Valeur |
|-------|--------|
| Modèle | `Profile` (name, description, extensions VSCode, settings) |
| Chemin partagé | `/data/profiles/{slug}.yaml` |
| Chemin utilisateur | `/data/users/{login}/profiles/{slug}.yaml` |
| Fonction | `profiles/repository.py :: ProfileRepository._write()` via `_atomic_dump()` |
| Format | YAML |
| Écriture | Atomique : tempfile + `os.replace()` |

Slug auto-généré par `slugify()`, dédupliqué avec suffixe `-N` si collision.

---

## 10. Sources distantes

### Recipe sources

| Champ | Valeur |
|-------|--------|
| Modèle | Liste d'URLs |
| Chemin | `/data/recipe-sources.yaml` |
| Fonction | `routes/recipe_sources.py :: _save_sources()` |
| Format | YAML — `sources: [url, ...]` |
| Écriture | Atomique : tempfile + `os.replace()` |

### Profile sources

| Champ | Valeur |
|-------|--------|
| Modèle | Liste d'URLs |
| Chemin | `/data/profile-sources.yaml` |
| Fonction | `routes/profile_sources.py :: _save_sources()` |
| Format | YAML — `sources: [url, ...]` |
| Écriture | Atomique : tempfile + `os.replace()` |

---

## 11. Tokens de jointure nœuds

| Champ | Valeur |
|-------|--------|
| Modèle | Token hashé + métadonnées (node_name, address, expires_at, used) |
| Chemin | `/data/tokens/{sha256(token)}.json` |
| Fonction | `nodes/enroll.py :: _atomic_write_json()` |
| Format | JSON |
| Écriture | Atomique : tempfile + `os.replace()` |

Token jamais en clair (seulement SHA256). TTL 1h. Marqué `used=true` après consommation unique.

---

## 12. Statut workspaces + routes Caddy

| Champ | Valeur |
|-------|--------|
| Modèle | `WorkspaceStatus` (ws_id, status, login, url, hostname, host_port, …) |
| Chemin | `/data/routes/{ws_id}.json` |
| Fonction | `devpod/service.py :: _write_status()`, `exposure/__init__.py :: _write_exposure()` |
| Format | JSON |
| Écriture | Atomique : tempfile + `os.replace()` |

Supprimé lors de `devpod delete`.

---

## 13. Logs workspaces

| Champ | Valeur |
|-------|--------|
| Modèle | Stdout + stderr du subprocess devpod |
| Chemin | `/data/logs/{login}/{ws_id}.log` |
| Fonction | `devpod/runner.py :: run_subprocess()` |
| Format | Texte brut UTF-8 |
| Écriture | Streamée ligne par ligne, flush après chaque ligne |

---

## 14. devcontainer.json temporaires

| Champ | Valeur |
|-------|--------|
| Modèle | devcontainer.json généré + copies des features recipes |
| Chemin | `/data/users/{login}/devpod/{ws_id}-dc-{rand}/devcontainer.json` |
| Fonction | `devpod/service.py :: _write_devcontainer()` |
| Format | JSON + Shell (copies recipes) |
| Écriture | `tempfile.mkdtemp()` + write_text + `shutil.copytree()` |

Auto-nettoyé en bloc `finally` via `shutil.rmtree()` après `devpod up`.

---

## Répertoires créés à l'initialisation

| Répertoire | Créé par | Permissions |
|------------|----------|-------------|
| `/data/users/{login}` | `config/store.py :: ensure_user_dir()` | `0o700` |
| `/data/users/{login}/keys/git` | idem | `0o700` |
| `/data/users/{login}/keys/workspaces` | idem | `0o700` |
| `/data/users/{login}/recipes` | idem | `0o700` |
| `/data/users/{login}/templates` | idem | `0o700` |
| `/data/users/{login}/devpod` | idem | `0o700` |
| `/data/profiles` | `profiles/repository.py` | — |
| `/data/recipes` | `recipes/sync.py` | — |
| `/data/routes` | `devpod/service.py` | — |
| `/data/logs/{login}` | `devpod/runner.py` | — |
| `/data/tokens` | `nodes/enroll.py` | `0o700` |
| `/data/certs/nodes/{node}` | `nodes/enroll.py` | `0o700` |
| `/data/keys/hosts` | `routes/admin.py` | — |

---

## Invariants de sécurité

- Toute construction de chemin sous `/data` passe par `safe_user_path()` (regex + `is_relative_to`) — concaténation de strings interdite.
- Toute écriture critique utilise l'écriture atomique 2-phases (tempfile dans le même répertoire + `os.replace()`) pour éviter toute corruption en cas de crash.
- Permissions fichiers sensibles : `0o600` (clés privées, `ca-key.pem`, `secrets.yaml`). Répertoires utilisateur : `0o700`.
- Tokens de jointure : jamais en clair, seulement leur SHA256.
