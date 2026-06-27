# Formalisme de résolution déclarative

## Principe

Harpocrate utilise un formalisme de résolution déclarative pour référencer des valeurs externes dans les configurations. Une référence déclare **une action** et **ses paramètres** — un loader résout la valeur au runtime.

```
${<action>://<paramètres>}
```

Ce formalisme est résolu par le loader au démarrage de l'application. Les références ne sont jamais évaluées en dehors du loader — elles restent des chaînes opaques jusqu'à la résolution.

---

## Actions disponibles

### `vault://` — Lecture d'un secret Harpocrate

```
${vault://<api_key_id>:<path>}
```

| Composant | Type | Description |
|---|---|---|
| `vault` | action | Lire un secret dans le coffre Harpocrate |
| `api_key_id` | string | Identifiant de l'API key dans la table de config locale |
| `path` | string | Chemin du secret dans le wallet (voir section Path) |

**Exemples** :

```
${vault://api1:anthropic_api_key}
${vault://api1:shared/slack_webhook}
${vault://prod:databases/postgres_password}
${vault://prod:alice@example.com/github_token}
```

### `env://` — Lecture d'une variable d'environnement / fichier `.env`

```
${env://<VAR_NAME>}
```

Lit la valeur de `<VAR_NAME>` depuis l'environnement du process (`os.environ`). En pratique, les variables sont chargées depuis un fichier `.env` via `python-dotenv` (ou équivalent) avant que le loader s'exécute — ce qui rend `env://` et "lire dans le `.env`" équivalents.

**Rôle principal** : alternative locale à `vault://` pour le développement et les environnements sans Harpocrate. La même clé de config peut pointer vers des sources différentes selon le contexte de déploiement :

```
dev  → ${env://ANTHROPIC_API_KEY}         # valeur dans .env local
prod → ${vault://api1:anthropic_api_key}  # valeur dans Harpocrate
```

**Comportement** : fail fast si `<VAR_NAME>` est absente de l'environnement — pas de valeur par défaut silencieuse.

**Exemples** :

```
${env://ANTHROPIC_API_KEY}
${env://DATABASE_URL}
${env://GITHUB_TOKEN}
```

---

## Formalisme du `path` dans `vault://`

Le `path` identifie un secret dans un wallet. Il suit la convention suivante :

```
{segment}/{segment}/{nom_du_secret}
```

### Règles

| Règle | Détail |
|---|---|
| Séparateur de niveaux | `/` |
| Caractères autorisés par segment | lettres, chiffres, `@`, `.`, `_`, `-` |
| Profondeur maximum | 10 niveaux |
| Segments vides | Interdits (`//` invalide) |
| Navigation relative | Interdite (`.` et `..` invalides) |
| Normalisation | Trim automatique des `/` en début et fin |

### Exemples

```
anthropic_api_key                    → secret à la racine du wallet
shared/slack_webhook                 → dossier "shared"
shared/databases/postgres_password   → deux niveaux de dossiers
alice@example.com/github_token       → dossier par email utilisateur
prod/api-keys/anthropic              → convention environnement/catégorie
```

### Conventions recommandées

```
# Secrets partagés entre tous les utilisateurs du wallet
shared/{nom_du_secret}

# Secrets personnels par utilisateur (isolation organisationnelle)
{email}/{nom_du_secret}

# Secrets par environnement
{env}/{nom_du_secret}            # ex: prod/anthropic_api_key

# Secrets par catégorie
{categorie}/{nom_du_secret}      # ex: databases/postgres_password

# Combiné
{env}/{categorie}/{nom_du_secret} # ex: prod/databases/postgres_password
```

> ⚠️ L'isolation par path est **organisationnelle, pas cryptographique**. Tous les utilisateurs ayant accès au wallet peuvent techniquement lire tous les secrets, quel que soit leur path. Pour une isolation cryptographique réelle, utiliser des wallets séparés.

---

## Table de config locale

La table de config locale associe chaque `api_key_id` à ses credentials Harpocrate. Elle est initialisée au démarrage depuis les variables d'amorçage.

### Variables d'amorçage

```bash
# Format : HARPOCRATE_API_TOKEN_{ID} et HARPOCRATE_API_URL_{ID}
HARPOCRATE_API_TOKEN_API1=hrp_1_...
HARPOCRATE_API_URL_API1=https://vault.example.com

HARPOCRATE_API_TOKEN_PROD=hrp_1_...
HARPOCRATE_API_URL_PROD=https://vault.example.com
```

### Structure en mémoire

```python
api_keys = {
    "api1": {"url": "https://vault.example.com", "token": "hrp_1_xxx..."},
    "prod": {"url": "https://vault.example.com", "token": "hrp_1_yyy..."},
}
```

---

## Implémentation du loader

```python
import re
import os
from harpocrate import VaultClient

# Patterns de reconnaissance
VAULT_PATTERN = re.compile(r'^\$\{vault://([^:]+):([^}]+)\}$')
ENV_PATTERN   = re.compile(r'^\$\{env://([^}]+)\}$')


def build_clients(api_keys: dict) -> dict:
    """Construit les clients Harpocrate depuis la table de config."""
    return {
        identifier: VaultClient(url=cfg["url"], token=cfg["token"])
        for identifier, cfg in api_keys.items()
    }


def resolve(value: str, clients: dict) -> str:
    """
    Résout une référence déclarative.
    Retourne la valeur inchangée si ce n'est pas une référence.
    """
    # vault://
    vault_match = VAULT_PATTERN.match(value)
    if vault_match:
        api_key_id = vault_match.group(1)
        path       = vault_match.group(2)
        if api_key_id not in clients:
            raise ValueError(f"Unknown vault api_key_id: '{api_key_id}'")
        return clients[api_key_id].get_secret(path)

    # env://
    env_match = ENV_PATTERN.match(value)
    if env_match:
        var_name = env_match.group(1)
        value = os.environ.get(var_name)
        if value is None:
            raise ValueError(f"Environment variable not found: '{var_name}'")
        return value

    # Valeur littérale — pas de résolution
    return value


def load_config(raw: dict, api_keys: dict) -> dict:
    """
    Résout toutes les références déclaratives dans un dictionnaire de config.
    Seules les valeurs de type string sont traitées.
    """
    clients = build_clients(api_keys)
    return {
        key: resolve(val, clients) if isinstance(val, str) else val
        for key, val in raw.items()
    }
```

### Usage

```python
# Charger les credentials depuis les variables d'amorçage
api_keys = {
    identifier.removeprefix("HARPOCRATE_API_TOKEN_").lower(): {
        "token": token,
        "url": os.environ[f"HARPOCRATE_API_URL_{identifier.removeprefix('HARPOCRATE_API_TOKEN_')}"],
    }
    for key, token in os.environ.items()
    if key.startswith("HARPOCRATE_API_TOKEN_")
}

# Résoudre la config de l'application
# Les références vault:// et env:// sont interchangeables —
# chaque environnement choisit sa source dans son propre fichier de config.

# En développement (config_dev.py) :
config = load_config(
    raw={
        "anthropic_api_key": "${env://ANTHROPIC_API_KEY}",   # lu depuis .env local
        "github_token":      "${env://GITHUB_TOKEN}",
        "database_url":      "${env://DATABASE_URL}",
        "log_level":         "debug",
    },
    api_keys={},  # pas de Harpocrate en dev
)

# En production (config_prod.py) :
config = load_config(
    raw={
        "anthropic_api_key": "${vault://api1:anthropic_api_key}",   # lu depuis Harpocrate
        "github_token":      "${vault://api1:shared/github_token}",
        "database_url":      "${vault://prod:databases/postgres_url}",
        "log_level":         "info",
    },
    api_keys=api_keys,
)
```

---

## Extensibilité

Le formalisme `${<action>://...}` est ouvert à d'autres actions :

```
${vault://api_key_id:path}    → Harpocrate — secret chiffré E2E (implémenté)
${env://VAR_NAME}             → Variable d'environnement / fichier .env (implémenté)
${file:///path/to/file}       → Fichier local (exemple futur)
${ssm://param_name}           → AWS Parameter Store (exemple futur)
${secret://k8s_secret_name}   → Kubernetes Secret (exemple futur)
```

Pour ajouter une nouvelle action, ajouter un pattern et un handler dans la fonction `resolve()`.

---

## Règles importantes pour l'implémentation

- **Résolution au démarrage uniquement** — pas de résolution à chaque requête
- **Résultat en RAM** — les valeurs résolues ne sont jamais persistées sur disque
- **Jamais dans les logs** — ne pas loguer les valeurs résolues, uniquement les clés
- **Fail fast** — si une référence ne peut pas être résolue, lever une exception au démarrage plutôt que de silencieusement retourner `None`
- **Une API key par identifiant** — ne pas partager une API key entre plusieurs `api_key_id`
