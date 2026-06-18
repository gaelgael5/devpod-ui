# Design — Gestion des API keys Harpocrate avec PIN utilisateur

Date : 2026-06-18  
Scope : Phase 2 — premier chantier (indépendant du reste de la migration vault)

---

## Objectif

Permettre à chaque utilisateur authentifié d'enregistrer ses API keys Harpocrate dans l'application. Ces clés sont chiffrées en base de données par une combinaison de deux facteurs :

- **KEK env** : clé maître 32 bytes stockée dans `.env` (`PORTAL_VAULT_KEK`), connue du serveur uniquement
- **PIN utilisateur** : code 6 chiffres connu de l'utilisateur uniquement, jamais stocké

Ni la base de données seule, ni le `.env` seul, ni le PIN seul ne permettent de déchiffrer les tokens. La surface d'attaque est réduite : un attaquant doit compromettre simultanément la DB, le `.env` et le PIN.

---

## Architecture globale

### Trois couches

**Cryptographie (backend)**

Une `master_key` 32 bytes aléatoire est générée par utilisateur à la création du PIN. Elle est chiffrée en DB via :

```
wrap_key = HKDF(input=PBKDF2(PIN, pin_salt), salt=KEK_env, length=32)
encrypted_master_key = AES-GCM(master_key, wrap_key)
```

Les API keys Harpocrate (`hrpv_*`) sont chiffrées individuellement :

```
encrypted_token = AES-GCM(hrpv_token, master_key)
```

La `master_key` elle-même n'est jamais persistée en clair — ni en DB, ni dans les logs, ni dans les cookies.

**Session RAM (backend)**

Après déverrouillage réussi, la `master_key` est conservée en mémoire dans un dict global :

```python
_vault_sessions: dict[str, bytes]  # session_id → master_key
```

Le `session_id` est l'identifiant de session Starlette (cookie HttpOnly signé côté client). Un redémarrage du serveur vide ce dict — l'utilisateur doit re-saisir son PIN.

**Frontend React**

Deux nouvelles routes publiques (non admin) :
- `/vault/unlock` — formulaire PIN, intercepté juste après le callback OIDC
- `/vault/keys` — CRUD des API keys Harpocrate

### Nouvelles tables DB

**`user_pin_config`**

| Colonne | Type | Description |
|---------|------|-------------|
| `login` | TEXT PK, FK users | Propriétaire |
| `encrypted_master_key` | BYTEA | AES-GCM(master_key, wrap_key(PIN)) |
| `pin_salt` | BYTEA | Sel PBKDF2 du PIN (16 bytes) |
| `encrypted_master_key_recovery` | BYTEA | AES-GCM(master_key, wrap_key(recovery_code)) |
| `recovery_salt` | BYTEA | Sel PBKDF2 du recovery code (16 bytes) |
| `pin_attempts` | INTEGER | Compteur de tentatives échouées |
| `locked_until` | TIMESTAMPTZ NULL | Verrouillage temporaire si > 5 tentatives |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

**`user_harpocrate_keys`**

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | SERIAL PK | |
| `login` | TEXT FK users CASCADE | Propriétaire |
| `identifier` | TEXT | Alias logique (`api1`, `prod`) |
| `encrypted_token` | BYTEA | AES-GCM(hrpv_token, master_key) |
| `url` | TEXT | URL du vault (`https://vault.yoops.org`) |
| `description` | TEXT | Texte libre |
| `created_at` | TIMESTAMPTZ | |
| UNIQUE | `(login, identifier)` | Un seul token par identifiant par user |

### Variable d'environnement

```bash
PORTAL_VAULT_KEK=<64 chars hex>  # 32 bytes, généré à l'installation : openssl rand -hex 32
```

Sans cette variable, le serveur refuse de démarrer si la feature vault est activée.

---

## Flows cryptographiques

### Première connexion — création du PIN

1. Après callback OIDC, le backend détecte l'absence de ligne dans `user_pin_config` → renvoie `{vault_status: "setup_required"}`
2. Frontend redirige vers `/vault/unlock/setup`
3. Utilisateur saisit son PIN 6 chiffres → `POST /api/vault/pin/setup {pin}`
4. Backend :
   ```
   master_key         = os.urandom(32)
   pin_salt           = os.urandom(16)
   pin_derived        = PBKDF2(PIN, pin_salt, iterations=600_000, hash=SHA-256) → 32 bytes
   kek_env            = bytes.fromhex(PORTAL_VAULT_KEK)
   wrap_key           = HKDF(input_key=pin_derived, salt=kek_env, length=32, hash=SHA-256)
   encrypted_mk       = AES-GCM(master_key, wrap_key)

   recovery_code      = secrets.token_urlsafe(18)  # ~24 chars, groupés par 4 à l'affichage
   recovery_salt      = os.urandom(16)
   recovery_derived   = PBKDF2(recovery_code, recovery_salt, iterations=600_000, hash=SHA-256)
   encrypted_mk_rec   = AES-GCM(master_key, recovery_derived)
   ```
5. Stocke en DB, place `master_key` en session RAM, retourne `{recovery_code}` **une seule fois**
6. Frontend affiche le recovery code groupé (ex: `ABCD-EFGH-IJKL-MNOP-QRST`) avec avertissement explicite et bouton « J'ai noté mon code de secours » pour continuer

### Connexions suivantes — déverrouillage

1. Après callback OIDC, `vault_status: "locked"` → frontend redirige vers `/vault/unlock`
2. Utilisateur saisit son PIN → `POST /api/vault/pin/unlock {pin}`
3. Backend :
   - Vérifie `locked_until` → si actif, rejette avec temps restant
   - Recalcule `wrap_key` identiquement
   - `AES-GCM-decrypt(encrypted_master_key, wrap_key)` → succès ou `InvalidTag`
   - Succès : `pin_attempts = 0`, `master_key` en session RAM, `200 OK`
   - Échec : `pin_attempts += 1` ; si `>= 5` : `locked_until = now + 15min` ; `401`
4. Frontend redirige vers l'app

### Oubli du PIN — recovery

1. Lien « Code de secours » sur la page de déverrouillage → `/vault/unlock/recover`
2. `POST /api/vault/pin/recover {recovery_code, new_pin}`
3. Backend :
   - `recovery_derived = PBKDF2(recovery_code, recovery_salt)`
   - `master_key = AES-GCM-decrypt(encrypted_master_key_recovery, recovery_derived)`
   - Si succès : rechiffre `master_key` avec nouveau PIN, génère **nouveau** recovery code, invalide l'ancien
   - Retourne `{recovery_code}` (nouveau, unique)
4. Frontend affiche le nouveau recovery code

---

## Page de gestion des API keys

Route : `/vault/keys` — accessible à tout utilisateur authentifié ET déverrouillé.

Si la session n'a pas de `master_key` en RAM → `403 {detail: "vault_locked"}` → frontend redirige vers `/vault/unlock`.

### Endpoints

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/api/vault/keys` | Liste `[{identifier, url, description, created_at}]` — token jamais retourné |
| `POST` | `/api/vault/keys` | Chiffre et stocke `{identifier, token, url, description}` |
| `DELETE` | `/api/vault/keys/{identifier}` | Supprime |
| `POST` | `/api/vault/keys/{identifier}/test` | Teste la connexion live (`VaultClient.whoami()`) |

### Flow d'ajout

1. Utilisateur saisit `identifier`, `token hrpv_*`, `url`, `description`
2. Backend : récupère `master_key` de la session RAM
3. Valide le token (format `hrpv_1_*`) et teste la connexion Harpocrate
4. `encrypted_token = AES-GCM(token.encode(), master_key)`
5. Stocke en DB

---

## Résolution dans le reste de l'app

Le resolver `portal/secrets/resolver.py` est étendu pour la source `vault://` multi-identifiants :

```
${vault://api1:mon/secret}
```

Flow :
1. Extraire `identifier=api1` et `path=mon/secret`
2. Récupérer `encrypted_token` en DB pour `(login, "api1")`
3. Déchiffrer avec `master_key` depuis la session RAM
4. Construire `VaultClient(token, url)` → `client.secrets.get("mon/secret")`

Si session non déverrouillée : erreur `VaultLockedError` — l'opération est refusée avec message explicite.

Les `VaultClient` instanciés peuvent être mis en cache dans la session RAM (`{session_id: {identifier: VaultClient}}`) pour éviter les appels réseau répétés à la wallet_key.

**Note d'implémentation :** `VaultClient` est synchrone (httpx bloquant). Tous les appels `client.secrets.get(...)` doivent être wrappés via `await anyio.to_thread.run_sync(...)` pour ne pas bloquer la boucle événementielle FastAPI.

---

## Gestion des erreurs

| Situation | Comportement |
|-----------|-------------|
| PIN incorrect | `401`, compteur incrémenté |
| 5 échecs consécutifs | Verrouillage 15 min, message avec temps restant |
| Recovery code incorrect | `401`, pas de verrouillage (code à usage unique, entropie suffisante) |
| `PORTAL_VAULT_KEK` absente au démarrage | Fail fast, message clair |
| Vault Harpocrate inaccessible au test | `503` avec détail de l'erreur réseau |
| Session expirée (restart serveur) | `403 vault_locked`, redirect transparent vers `/vault/unlock` |
| Token hrpv_* invalide à l'ajout | `422` avec message de validation |

---

## Sécurité — points non négociables

- `PORTAL_VAULT_KEK` : jamais dans git, jamais dans les logs, permissions `0o600` sur le fichier `.env`
- `master_key` : jamais loggée, jamais sérialisée sur disque, jamais dans un cookie
- `encrypted_token` en DB : jamais retourné en clair par l'API
- Le recovery code est affiché **une seule fois** — pas de route pour le récupérer ensuite
- PBKDF2 avec 600 000 itérations (recommandation OWASP 2023 pour SHA-256)
- AES-GCM avec nonce 12 bytes aléatoires, nonce stocké préfixé au chiffré

---

## Tests obligatoires

- Setup PIN → master_key déchiffrée correctement
- Unlock correct → session RAM peuplée
- Unlock incorrect × 5 → verrouillage 15 min
- Recovery code → nouveau PIN fonctionne, ancien recovery invalide
- Ajout API key → token chiffré en DB, jamais retourné en clair
- Résolution `${vault://api1:path}` → VaultClient appelé avec le bon token
- Session absente → `403 vault_locked` sur tous les endpoints protégés
- `PORTAL_VAULT_KEK` absente → fail fast au démarrage
