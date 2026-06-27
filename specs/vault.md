# Migration vers le coffre Harpocrate

## Contexte

Cette application stocke actuellement des secrets (API keys, mots de passe, tokens, certificats) directement dans des fichiers `.env` ou autre fichier yaml, dans des configs,  **Tout cela doit disparaître.**

Désormais, les secrets sont centralisés dans **Harpocrate**, un coffre-fort end-to-end encrypted accessible via API REST.

Ta mission : nettoyer toute la logique existante de gestion de secrets et la remplacer par une consommation propre du coffre.


## Le coffre Harpocrate

**URL** : — prod : `https://vault.yoops.org`

**Spec** 
- D:\srcs\devpod-ui\Sdk\harpocrate-0.6.0\README.md
- D:\srcs\devpod-ui\specs\internal_resolution-formalism.md

Commence par lire ce répertoire. 

## Modèle cryptographique (à comprendre avant de coder)

Harpocrate est **end-to-end encrypted** : le serveur ne stocke et ne déchiffre jamais les valeurs en clair.

- L'authentification se fait avec une **API key** au format `hrpv_1_*`
- Ce token contient deux composants distincts encodés dans sa structure : un secret d'authentification (utilisé par le serveur pour valider l'appel) et une clé de déchiffrement (utilisée localement par le client pour déchiffrer les réponses)
- Le token complet `hrpv_1_*` est envoyé dans le header `Authorization: Bearer` pour l'authentification
- Quand tu lis un secret, le serveur renvoie une valeur **chiffrée en AES-GCM**
- Tu déchiffres localement avec la clé de déchiffrement extraite du token — cette clé ne quitte jamais la RAM du client

**Tu ne fais jamais ce travail à la main**. Tu utilises le SDK officiel qui gère l'extraction des composants du token, l'authentification, le déchiffrement local, et les bonnes pratiques de sécurité.


## SDK officiel

le SDK est ici : D:\srcs\devpod-ui\Sdk\harpocrate-0.6.0

## Convention de référence aux secrets

Dans tout le code et toutes les configs de l'application, les références aux secrets utilisent ce format :

Secret à la racine d'un wallet :
```
${vault://<identifiant_api_key>:<nom_du_secret>}
```

Secret dans un sous-répertoire (chemin virtuel) :
```
${vault://<identifiant_api_key>:<chemin>/<nom_du_secret>}
```

**Exemples :**
```yaml
# docker-compose.yml
environment:
  GITHUB_TOKEN: ${vault://api1:GITHUB_TOKEN}
  ANTHROPIC_API_KEY: ${vault://api1:ANTHROPIC_API_KEY}
  DATABASE_PASSWORD: ${vault://api2:POSTGRES_PASSWORD}
  # Avec sous-répertoire (organisation par identité ou contexte) :
  PERSONAL_OPENAI_KEY: ${vault://api1:gaelgael5@gmail.com/OPENAI_API_KEY}
```

```python
# config.py
config = {
    "github_token": "${vault://api1:GITHUB_TOKEN}",
    "anthropic_api_key": "${vault://api1:ANTHROPIC_API_KEY}",
}
```

- `vault` = source de résolution (Harpocrate)
- `<identifiant_api_key>` = alias logique local à l'application (voir section suivante)
- `<chemin>/<nom_du_secret>` = chemin virtuel dans le wallet, séparateur `/`

L'alias n'est pas transmis à Harpocrate — c'est un alias purement local. Le wallet n'a pas besoin d'être précisé : chaque API key Harpocrate est scopée à un seul wallet, l'association est implicite.

### Découverte de l'arborescence

Pour lister les secrets et sous-répertoires disponibles depuis un wallet :
- `GET /v1/wallets/{wallet_id}/tree?path=/` — retourne les sous-dossiers directs et le nombre de secrets à un niveau donné
- `GET /v1/wallets/{wallet_id}/secrets?path=/chemin/` — retourne les secrets directs d'un répertoire (non récursif)
- `GET /v1/wallets/{wallet_id}/secrets` — retourne tous les secrets du wallet (liste plate, paginée)


## Table de configuration des API keys

L'application doit maintenir une **table de configuration locale** des API keys Harpocrate qui lui sont attribuées.

Cette table associe chaque identifiant logique à ses credentials :

| Champ | Description |
|---|---|
| `identifier` | Alias logique dans `${vault://...}` (ex: `api1`, `github`, `prod-shared`) |
| `url` | URL du coffre Harpocrate |
| `token` | Token API key complet au format `hrpv_1_*` |
| `description` | Texte libre pour rappeler à quoi sert cette key |

**À toi de décider** comment matérialiser cette table en fonction du projet :

- Application déjà connectée à une base SQL → table dédiée
- Application avec un secrets manager local (Vault Agent, sealed secrets, etc.) → adapter à ce système

Quel que soit le format, **cette table contient des credentials sensibles** :
- Permissions strictes sur le fichier (`chmod 600` si fichier)
- Pas de commit dans git
- Backup conjoint avec les autres secrets de l'application
- Si possible, chiffrement au repos


## Loader de résolution

L'application doit avoir un **mécanisme de résolution** qui :

1. Détecte les chaînes au format `${vault://<id>:<clé>}` dans la config et l'environnement
2. Lookup `<id>` dans la table de config locale → récupère url + token
3. Appelle Harpocrate via le SDK pour récupérer le secret `<clé>`
4. Remplace la chaîne par la valeur déchiffrée
5. Cache les résultats en RAM pendant la durée de vie du process pour éviter les appels redondants

Le moment de la résolution dépend du type d'application :

- Application qui démarre une fois avec ses secrets en RAM → résolution au démarrage, valeurs gardées dans le process
- Application long-running qui peut subir des rotations → résolution paresseuse + invalidation de cache si `401` reçu de l'API
- Containers avec init script (Docker, Swarm) → résolution dans l'entrypoint, injection en env vars du process applicatif

À toi de choisir le pattern adapté.


## Cache et invalidation

- Garde les valeurs déchiffrées en RAM, pas sur disque
- Cache valide jusqu'à fin de process ou jusqu'à un `401`/`403` du coffre
- Si `401` : refresh la table de config (la key a peut-être été révoquée), re-tenter une fois, sinon échec explicite
- Pas de cache négatif (un secret introuvable n'est pas mis en cache)


## Gestion des erreurs

Le coffre peut être indisponible (maintenance, réseau, etc.). L'application doit gérer proprement :

- **Au démarrage** : si le coffre est inaccessible et que l'application a besoin de secrets pour fonctionner, échec rapide avec un message d'erreur clair (`Harpocrate unreachable at startup, cannot resolve secrets`)
- **En runtime** : retry avec backoff exponentiel sur les erreurs réseau transitoires, échec définitif après N tentatives
- **Token révoqué** : message d'erreur explicite indiquant quel alias (`api1`, `api2`) a été refusé
- **Secret introuvable** : message indiquant le nom du secret recherché et l'alias associé

Ne jamais logger en clair :
- Le contenu du token API key (`hrpv_1_*`)
- Les valeurs déchiffrées des secrets
- La clé de déchiffrement extraite du token

Loguer librement :
- Les alias logiques (`api1`, `api2`)
- Les noms de secrets (`GITHUB_TOKEN`, `ANTHROPIC_API_KEY`)
- Les codes d'erreur HTTP du coffre


## Plan de migration

Voici ce que tu dois faire concrètement, dans cet ordre :

1. **Inventaire** : liste tous les endroits où des secrets sont actuellement gérés
   - Fichiers `.env` et `.env.example`
   - Variables hardcodées dans le code source
   - Configs YAML/JSON contenant des valeurs sensibles
   - Logique custom de gestion de secrets (lecture de fichiers chiffrés, intégration cloud secrets manager, etc.)
   - Templates docker-compose, Helm charts, manifests Kubernetes
   - Scripts d'install / bootstrap / CI

2. **Conception de la table de config** : choisis le format adapté au projet (fichier YAML, table SQL, etc.) et crée la structure

3. **Implémentation du loader** : code le mécanisme de résolution `${vault://...}` adapté au cycle de vie de l'application

4. **Migration** : remplace toutes les occurrences inventoriées par des références `${vault://...}`. Les vraies valeurs des secrets seront placées dans le coffre Harpocrate (pas dans le code, pas dans la table de config).

5. **Suppression** : supprime tout l'ancien code de gestion de secrets (lecture de `.env` pour des secrets, intégration custom, etc.). Le seul mécanisme restant doit être le loader Harpocrate.

6. **Documentation** : mets à jour le README pour expliquer
   - Où se trouve la table de config locale
   - Comment ajouter une nouvelle API key Harpocrate au projet
   - Comment référencer un secret dans le code
   - Comment l'application résout les secrets au démarrage

7. **Tests** : assure-toi que les tests d'intégration utilisent une instance Harpocrate de test (ou un mock du SDK) et que les tests unitaires ne dépendent plus de secrets en clair.


## Variables d'environnement attendues

Pour t'amorcer, l'opérateur a placé ces variables dans ton environnement (fichier `.env` du projet, secrets Docker Swarm, ou équivalent) :

```bash
# Pour chaque API key Harpocrate attribuée à cette application :
HARPOCRATE_API_TOKEN_<IDENTIFIER>=hrpv_1_...   # token complet
HARPOCRATE_API_URL_<IDENTIFIER>=https://vault.yoops.org

# Exemple :
# HARPOCRATE_API_TOKEN_API1=hrpv_1_abc...xyz
# HARPOCRATE_API_URL_API1=https://vault.yoops.org
```

Au démarrage du loader, lis ces variables pour peupler la table de config initiale, **ou** importe-les depuis un fichier de config maintenu par l'opérateur (à toi de choisir selon le projet).

Si aucune variable `HARPOCRATE_API_TOKEN_*` n'est présente au démarrage, échoue clairement : `No Harpocrate API key configured, cannot resolve secrets`.


## Intégration Next.js — pièges de compilation

`instrumentation.ts` est compilé par webpack pour **trois** contextes distincts : Node.js serveur, Edge runtime, et client. Même si le code contient un guard runtime (`if (process.env.NEXT_RUNTIME !== 'nodejs') return`), webpack analyse statiquement toutes les dépendances, y compris les dynamic imports comme `await import('./lib/vault')`.

### Règle 1 : ne jamais utiliser le préfixe `node:`

```ts
// ❌ webpack ne connaît pas le scheme node: par défaut
import { createDecipheriv } from 'node:crypto';

// ✓ webpack sait résoudre le built-in sans préfixe
import { createDecipheriv } from 'crypto';
```

### Règle 2 : configurer webpack par runtime dans `next.config.js`

```js
webpack: (config, { nextRuntime }) => {
  if (nextRuntime === 'nodejs') {
    // Node.js serveur — crypto est disponible à l'exécution, le marquer external
    // pour que webpack émette require('crypto') sans tenter de le bundler.
    const existing = config.externals;
    config.externals = [
      { crypto: 'commonjs crypto' },
      ...(Array.isArray(existing) ? existing : existing ? [existing] : []),
    ];
  } else {
    // Edge ou client — pas de built-ins Node.js.
    // vault.ts ne s'exécute jamais dans ces contextes grâce au guard NEXT_RUNTIME.
    config.resolve.fallback = { ...config.resolve.fallback, crypto: false };
  }
  return config;
},
```

Pourquoi `nextRuntime` et pas `isServer` : `isServer` est `true` pour Node.js **et** Edge. Le guard `nextRuntime === 'nodejs'` cible uniquement le bundle Node.js où `require('crypto')` est disponible à l'exécution.

`resolve.fallback: { crypto: false }` pour Edge/client indique à webpack de ne fournir aucun polyfill — il génère un module vide. Aucune erreur de build, aucune exécution réelle (guard runtime).


## Intégration backend Dockerfile — dépendance locale uv

Quand `pyproject.toml` déclare une dépendance locale via `[tool.uv.sources]` (ex: `harpocrate = { path = "src/role_builder/secrets", editable = true }`), le répertoire du package doit être présent **avant** de lancer `uv pip install`.

Le pattern habituel "copier le manifest → installer → copier le source" casse silencieusement :

```dockerfile
# ❌ src/role_builder/secrets/ absent au moment de l'install
COPY backend/pyproject.toml backend/uv.lock /app/
RUN uv pip install --system --no-cache .   # error: Distribution not found at: file:///app/src/role_builder/secrets

COPY backend/src/ /app/src/
```

```dockerfile
# ✓ copier le package local avant l'install
COPY backend/pyproject.toml backend/uv.lock /app/
COPY backend/src/role_builder/secrets/ /app/src/role_builder/secrets/
RUN uv pip install --system --no-cache .

COPY backend/src/ /app/src/   # écrase proprement, même contenu
```

Le `COPY backend/src/` final réécrit le répertoire `secrets/` avec le même contenu — c'est intentionnel et sans effet de bord.


## Critères de réussite

Avant de considérer la migration terminée :

- Aucun secret n'est plus en clair dans le code, la config, ou les fichiers `.env`
- Toute valeur sensible est référencée par `${vault://<id>:<clé>}`
- Le loader résout ces références au moment approprié
- L'application démarre correctement avec un token valide et échoue proprement avec un token invalide
- L'ancien code de gestion de secrets a été supprimé, pas désactivé
- Le README documente le nouveau fonctionnement
- Les tests passent


## Points d'attention

- **Tu décides** comment matérialiser la table de config et le loader. Adapte au projet.
- **Tu décides** comment supprimer l'ancien code. Sois agressif : pas de "au cas où", pas de code mort, pas de fallback vers les anciens secrets.
- **N'invente pas** d'endpoints Harpocrate : utilise uniquement ceux du spec OpenAPI (`/v1/openapi-api-key.json`).
- **Ne jamais construire** le header Authorization à la main sans avoir lu le spec OpenAPI : si tu n'utilises pas le SDK, la séparation entre secret d'authentification et clé de déchiffrement doit être respectée exactement.
- **Si le projet a des dépendances** sur des secrets dynamiques (rotation fréquente, secrets éphémères), gère le cache avec invalidation et retry plutôt qu'un simple lookup au démarrage.


## Pièges opérationnels confirmés en production

### `whoami()` retourne 404 sur vault.yoops.org

La méthode `VaultClient.whoami()` du SDK appelle `GET /v1/api-keys/{api_key_id}` — cet endpoint **n'existe pas** sur vault.yoops.org et retourne systématiquement `{"detail": "Not Found"}`.

Pour tester la validité d'un token, utiliser `_resolve_wallet_id()` qui appelle `GET /v1/api-keys/{api_key_id}/wallet-id` et retourne le `wallet_id` avec un 200 si le token est valide :

```python
# ❌ whoami() → GET /v1/api-keys/{id} → 404 sur vault.yoops.org
info = client.whoami()

# ✓ _resolve_wallet_id() → GET /v1/api-keys/{id}/wallet-id → 200
wallet_id = client._resolve_wallet_id()
return {
    "api_key_id": str(client._parsed.api_key_id),
    "wallet_id": str(wallet_id),
    "permissions": client._parsed.permissions,
}
```

Ce comportement est confirmé par le projet de référence `rag/` qui évite explicitement `whoami()` pour la même raison.

### Docker bridge + IPv6 : urllib3 échoue sans fallback

Dans un container Docker sur réseau bridge, l'IPv6 n'est pas routé. Le DNS retourne des adresses AAAA (IPv6) **et** A (IPv4) pour `vault.yoops.org`. Python/urllib3 tente l'IPv6 en premier et **abandonne sans fallback**, contrairement à curl.

Fix à appliquer au démarrage du process Python (avant tout import de librairie réseau) :

```python
import socket as _socket

_orig_getaddrinfo = _socket.getaddrinfo

def _prefer_ipv4(*args: object, **kwargs: object) -> object:
    results = _orig_getaddrinfo(*args, **kwargs)  # type: ignore[arg-type]
    family = args[2] if len(args) > 2 else kwargs.get("family", 0)
    if family == 0:
        ipv4 = [r for r in results if r[0] == _socket.AF_INET]
        if ipv4:
            return ipv4 + [r for r in results if r[0] != _socket.AF_INET]
    return results

_socket.getaddrinfo = _prefer_ipv4  # type: ignore[assignment]
```

Placer ce bloc **après** tous les imports (pour passer ruff E402), mais avant toute connexion réseau runtime. urllib3 et httpx ne capturent pas `getaddrinfo` à l'import — le patch reste efficace.

Bonne migration.
