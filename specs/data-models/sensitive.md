# Données sensibles — inventaire et pièges de migration

Objectif : identifier chaque champ sensible dans les modèles, qualifier le risque,
documenter la protection actuelle (filesystem) et la stratégie requise en base.

---

## Niveaux de sensibilité

| Niveau | Définition |
|--------|-----------|
| **CRITIQUE** | Compromission → contrôle total du système ou accès à l'ensemble des secrets |
| **ÉLEVÉ** | Compromission → accès non autorisé aux ressources d'un utilisateur ou d'un nœud |
| **MOYEN** | Compromission → information utile à une attaque secondaire, ou accès partiel |
| **FAIBLE** | Donnée publique ou non exploitable seule |

---

## Inventaire par table

### `global_config`

| Colonne | Niveau | Nature | Protection actuelle | Stratégie DB |
|---------|--------|--------|---------------------|--------------|
| `oidc_client_secret` | **CRITIQUE** | Secret OAuth2 — permet d'usurper le client OIDC | Fichier `0o600`, type `Secret`, `.reveal()` uniquement à authlib | Colonne chiffrée (KEK) ou stockage Vault transit |
| `harpocrate_api_key` | **CRITIQUE** | Clé d'accès au vault global — donne accès à l'ensemble des secrets gérés | Fichier `0o600`, type `Secret`, redaction logs | Colonne chiffrée (KEK) — jamais en clair en base |
| `cf_api_key` | **ÉLEVÉ** | Clé API Cloudflare — manipulation DNS, tunnel | Fichier `0o600`, type `Secret` | Colonne chiffrée (KEK) |

### `hypervisors`

| Colonne | Niveau | Nature | Protection actuelle | Stratégie DB |
|---------|--------|--------|---------------------|--------------|
| `password` | **ÉLEVÉ** | Mot de passe API Proxmox — accès complet aux VMs du nœud | Fichier `0o600`, type `Secret` | Colonne chiffrée (KEK) — envisager Vault |
| `ssh_key_path` | **MOYEN** | Chemin vers clé privée SSH hyperviseur sur filesystem | Fichier config `0o600` | Colonne TEXT normale — le fichier référencé reste sur le volume |

### `hosts`

| Colonne | Niveau | Nature | Protection actuelle | Stratégie DB |
|---------|--------|--------|---------------------|--------------|
| `key_path` | **MOYEN** | Chemin vers clé privée SSH hôte | Config `0o600` | Colonne TEXT — le fichier référencé reste `0o600` sur le volume |
| `public_key` | **FAIBLE** | Clé publique SSH — non sensible en soi | Aucune | Colonne TEXT normale |

### `users`

| Colonne | Niveau | Nature | Protection actuelle | Stratégie DB |
|---------|--------|--------|---------------------|--------------|
| `harpocrate_api_key` | **CRITIQUE** | Clé d'API personnelle Harpocrate — accès à tous les secrets de l'utilisateur | Fichier user `0o600`, type `Secret`, redaction logs | Colonne chiffrée (KEK) — clé de chiffrement séparée par user recommandée |
| `secret_ns` | **ÉLEVÉ** | UUID namespace Harpocrate — combiné à la clé API, donne accès aux secrets | Fichier user `0o600` | Ne pas exposer via API publique ; RLS PostgreSQL pour isolation par login |

### `git_credentials`

| Colonne | Niveau | Nature | Protection actuelle | Stratégie DB |
|---------|--------|--------|---------------------|--------------|
| `token` | **ÉLEVÉ** | Token Git (GitHub/GitLab) — accès en lecture/écriture aux repos | Fichier user `0o600`, type `Secret` | Colonne chiffrée (KEK par user) |
| `key_path` | **MOYEN** | Chemin vers clé privée SSH Git | Config user `0o600` | Colonne TEXT — le fichier référencé reste sur le volume |
| `public_key` | **FAIBLE** | Clé publique SSH Git — destinée à être déposée sur GitHub/GitLab | Aucune (c'est une donnée publique par design) | Colonne TEXT normale |

### `workspaces`

| Colonne | Niveau | Nature | Protection actuelle | Stratégie DB |
|---------|--------|--------|---------------------|--------------|
| `env` | **VARIABLE** | JSONB de variables d'environnement libres — peut contenir des secrets selon l'utilisateur | Fichier user `0o600` ; aucune redaction automatique | **Piège majeur** : ne pas stocker en clair. Chiffrer la colonne entière, ou interdire les secrets dans `env` et forcer l'usage de `requires_secrets`. |

### `workspace_ssh_keys`

| Colonne | Niveau | Nature | Protection actuelle | Stratégie DB |
|---------|--------|--------|---------------------|--------------|
| `private_key_path` | **MOYEN** | Chemin vers clé privée Ed25519 workspace — le fichier ne quitte jamais le serveur | Fichier `0o600` | Colonne TEXT ; la clé privée reste sur le volume. Migration vers `BYTEA` chiffré si stockage DB |
| `public_key` | **FAIBLE** | Clé publique Ed25519 workspace | Aucune | Colonne TEXT normale |

### `recipes`

| Colonne | Niveau | Nature | Protection actuelle | Stratégie DB |
|---------|--------|--------|---------------------|--------------|
| `install_sh` / `start_sh` | **MOYEN** | Scripts shell — peuvent contenir des valeurs hardcodées par inadvertance | Fichier `0o755` admin-only | Audit à la création ; pas de chiffrement requis si validation stricte à l'écriture |
| `feature_json` | **FAIBLE** | Configuration devcontainer — rarement sensible | Fichier admin-only | Colonne JSONB normale |

### `recipe_secret_refs`

| Colonne | Niveau | Nature | Protection actuelle | Stratégie DB |
|---------|--------|--------|---------------------|--------------|
| `path` | **MOYEN** | Chemin Harpocrate vers un secret — révèle la topologie des secrets d'une recette | Fichier admin `0o600` | Colonne TEXT ; accès réservé aux admins via RLS |

### `node_certificates`

| Colonne | Niveau | Nature | Protection actuelle | Stratégie DB |
|---------|--------|--------|---------------------|--------------|
| `cert_pem` | **MOYEN** | Certificat X.509 — public par nature mais révèle IP + nom du nœud | Fichier `0o644` | Colonne TEXT ; contrôle d'accès admin uniquement via RLS |

### `node_join_tokens`

| Colonne | Niveau | Nature | Protection actuelle | Stratégie DB |
|---------|--------|--------|---------------------|--------------|
| `token_hash` | **FAIBLE** | SHA256 du token — non réversible (token = 32 bytes aléatoires) | Token en clair retourné une seule fois, jamais stocké | Colonne TEXT normale ; index sur la PK suffit |

---

## Données absentes des tables mais sensibles sur le filesystem

Ces données **ne migrent pas en base** — elles restent sur le volume `/data`.
La table DB stocke uniquement le chemin (pointeur).

| Fichier | Niveau | Raison de ne pas migrer |
|---------|--------|------------------------|
| `/data/certs/ca/ca-key.pem` | **CRITIQUE** | Clé privée de la CA interne — compromission = faux certificats nœuds. Ne doit jamais quitter le volume chiffré. |
| `/data/keys/hosts/{name}_ed25519` | **ÉLEVÉ** | Clé privée SSH hôte — accès direct aux VMs |
| `/data/users/{login}/keys/workspaces/{ws}/id_ed25519` | **ÉLEVÉ** | Clé privée SSH workspace — accès au container de l'utilisateur |
| `/data/users/{login}/keys/git/{cred}/id_ed25519` | **ÉLEVÉ** | Clé privée SSH Git — accès aux repos |
| `/data/users/{login}/keys/hypervisors/{name}_ed25519` | **ÉLEVÉ** | Clé privée SSH hyperviseur |

---

## Pièges de migration

### 1. `workspaces.env` — JSONB libre non chiffré

**Piège** : un utilisateur peut stocker `MY_API_KEY=xxx` dans `env`. En base non chiffrée,
cette valeur est en clair dans tous les dumps, WAL, réplicas.

**Règle** : chiffrer la colonne `env` avec `pg_crypto` (fonction `pgp_sym_encrypt`/`pgp_sym_decrypt`)
ou migrer les valeurs sensibles vers `recipe_secret_refs` avant insertion.

### 2. `oidc_client_secret` / `harpocrate_api_key` / `cf_api_key` — colonnes CRITIQUE dans `global_config`

**Piège** : un `SELECT * FROM global_config` dans un log de requête, un dump non filtré,
ou un accès DBA compromet immédiatement le système entier.

**Règle** : ces colonnes doivent être chiffrées côté application avant insertion
(pattern : chiffrement envelope avec KEK stockée hors DB — ex. fichier `0o600` sur le volume,
ou Vault Transit). Jamais exposées dans les vues, les logs de requêtes, ou les exports.

### 3. `users.harpocrate_api_key` — isolation par utilisateur

**Piège** : une KEK globale chiffrerait toutes les clés API avec la même clé.
Si la KEK fuit, toutes les clés fuient.

**Règle** : KEK dérivée par utilisateur (`HKDF(master_key, login)`) ou clé par utilisateur
dans Vault. Un accès compromis sur un user ne doit pas propager aux autres.

### 4. Chemins de clés privées — pointeurs sans validation

**Piège** : `key_path` est un chemin libre. En base, un attaquant ayant accès en écriture
peut rediriger vers un fichier arbitraire (ex. `/data/certs/ca/ca-key.pem`).

**Règle** : `safe_user_path()` doit être appliqué à la lecture, pas seulement à l'écriture.
En base : contrainte CHECK sur le préfixe autorisé (`/data/keys/` ou `/data/users/{login}/`).

### 5. `node_join_tokens` — cleanup des tokens expirés

**Piège** : sans purge, la table accumule des tokens `used=true` ou expirés. Un attaquant
avec accès DB voit l'historique complet des enrôlements (node_name, address, date).

**Règle** : job de purge périodique `DELETE WHERE expires_at < now() - INTERVAL '7 days'`.

### 6. `recipe_secret_refs.path` — méta-information sur les secrets

**Piège** : le chemin Harpocrate révèle la structure (`devpod/tools/aider/api_key`).
Un attaquant connaissant la structure peut cibler les secrets.

**Règle** : accès en lecture réservé au propriétaire de la recette + admins via RLS.
Ne jamais exposer dans les réponses API destinées aux utilisateurs non-admins.

### 7. `global_config.oidc_scopes` — tableau TEXT[] non chiffré

Pas sensible en soi, mais **adjacent** aux colonnes CRITIQUE dans la même table.
Éviter que les dumps partiels ("juste les scopes OIDC") ne contiennent accidentellement
les colonnes voisines (`oidc_client_secret`).

**Règle** : décomposer `global_config` en deux tables si la politique d'accès le requiert :
`global_config_public` (paramètres non sensibles) + `global_config_secrets` (CRITIQUE uniquement).

---

## Recommandations techniques pour la migration

| Mécanisme | Usage recommandé |
|-----------|-----------------|
| `pgp_sym_encrypt(val, key)` (pg_crypto) | Colonnes ÉLEVÉ : `token`, `password`, `harpocrate_api_key` user |
| Chiffrement applicatif avant INSERT | Colonnes CRITIQUE : `oidc_client_secret`, `harpocrate_api_key` global, `cf_api_key` |
| RLS PostgreSQL (`USING (login = current_user)`) | Isolation des lignes par propriétaire : `git_credentials`, `workspaces`, `profiles`, `workspace_ssh_keys` |
| Vue filtrée (`CREATE VIEW … AS SELECT … EXCEPT secret_col`) | Exposer les tables aux rôles applicatifs sans exposer les colonnes sensibles |
| Volume chiffré (LUKS/dm-crypt) | Clés privées sur filesystem — indépendant de la DB |
| `pg_audit` | Tracer les SELECT sur les colonnes CRITIQUE (`global_config`, `users`) |
