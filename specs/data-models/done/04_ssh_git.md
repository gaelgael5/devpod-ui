# 04 — Clés SSH git credentials

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | Paire Ed25519 |
| Chemin | `/data/users/{login}/keys/git/{cred_name}/id_ed25519` + `.pub` |
| Fonction | `ssh_keys.py :: generate_git_credential_ssh_key()` |
| Format | PEM (privée `0o600`), OpenSSH (publique `0o644`) |
| Écriture | Atomique : tempfile + `os.replace()` |

Générée lors de la création d'un `GitCredential` de type `ssh`. La clé publique est fournie à l'utilisateur pour dépôt sur GitHub/GitLab. La clé privée reste sur le serveur.

---

## Modèle Python (Pydantic v2)

Pas de modèle Pydantic dédié — piloté par `ssh_keys.py`. Modèle logique :

```python
from __future__ import annotations
from pydantic import BaseModel, ConfigDict

class GitCredentialSshKey(BaseModel):
    """Représentation logique d'une paire SSH pour credential Git."""
    model_config = ConfigDict(extra="forbid")

    login: str           # propriétaire
    cred_name: str       # nom du GitCredential associé
    public_key: str      # contenu OpenSSH (à déposer sur GitHub/GitLab)
    private_key_path: str  # chemin absolu vers id_ed25519 (0o600)
```

Fonctions associées dans `ssh_keys.py` :

```python
def generate_git_credential_ssh_key(login: str, cred_name: str) -> tuple[str, str]:
    """Génère la paire. Retourne (key_path, public_key)."""
    ...

def derive_git_credential_public_key(key_path: str) -> str:
    """Relit la clé privée et en dérive la clé publique OpenSSH."""
    ...
```

---

## Tables SQL équivalentes

```sql
-- La clé SSH est intégrée directement dans la table git_credentials (02_user_config) :
--
--   git_credentials.key_path   → chemin filesystem vers id_ed25519 (0o600)
--   git_credentials.public_key → contenu OpenSSH .pub (à déposer sur GitHub/GitLab)
--
-- Pas de table séparée requise : les deux colonnes couvrent entièrement le modèle
-- GitCredentialSshKey ci-dessus. Le login + cred_name est la FK naturelle.
--
-- Rappel de la définition dans 02_user_config :
--
-- CREATE TABLE git_credentials (
--     id         SERIAL PRIMARY KEY,
--     login      TEXT NOT NULL REFERENCES users(login) ON DELETE CASCADE,
--     name       TEXT NOT NULL,           -- cred_name
--     host       TEXT NOT NULL,
--     kind       TEXT NOT NULL,           -- 'ssh' | 'token'
--     key_path   TEXT NOT NULL DEFAULT '',  -- chemin id_ed25519 (0o600)
--     public_key TEXT NOT NULL DEFAULT '',  -- OpenSSH .pub
--     username   TEXT NOT NULL DEFAULT '',
--     token      TEXT NOT NULL DEFAULT '',  -- chiffré (kind=token)
--     UNIQUE (login, name)
-- );
```
