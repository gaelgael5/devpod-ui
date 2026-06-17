# 03 — Clés SSH workspace

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | Paire Ed25519 (privée + publique) |
| Chemin | `/data/users/{login}/keys/workspaces/{workspace}/id_ed25519` + `.pub` |
| Fonction | `ssh_keys.py :: ensure_workspace_ssh_key()` |
| Format | PEM (privée `0o600`), OpenSSH (publique `0o644`) |
| Écriture | Atomique : tempfile + `os.replace()` |

Générée automatiquement à la première connexion SSH au workspace. La clé privée ne quitte jamais le serveur.

---

## Modèle Python (Pydantic v2)

Il n'y a pas de modèle Pydantic dédié — la paire est gérée directement via le filesystem par `ssh_keys.py`.
Le modèle logique de la donnée est le suivant :

```python
from __future__ import annotations
from pydantic import BaseModel, ConfigDict

class WorkspaceSshKey(BaseModel):
    """Représentation logique d'une paire SSH workspace (non sérialisée telle quelle)."""
    model_config = ConfigDict(extra="forbid")

    login: str           # propriétaire
    workspace_name: str  # nom du workspace (DNS-safe)
    public_key: str      # contenu OpenSSH (type + base64 + comment)
    private_key_path: str  # chemin absolu vers id_ed25519 (0o600)
```

Fonctions associées dans `ssh_keys.py` :

```python
def ensure_workspace_ssh_key(login: str, workspace_name: str) -> str:
    """Génère la paire si absente. Retourne la clé publique OpenSSH."""
    ...

def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    """Écriture atomique tempfile + os.replace, puis chmod."""
    ...
```

---

## Tables SQL équivalentes

```sql
CREATE TABLE workspace_ssh_keys (
    id               SERIAL PRIMARY KEY,
    login            TEXT NOT NULL,
    workspace_name   TEXT NOT NULL,
    -- La clé privée reste sur le filesystem ; on stocke son chemin et la clé publique.
    private_key_path TEXT NOT NULL,          -- chemin absolu id_ed25519, 0o600
    public_key       TEXT NOT NULL,          -- contenu OpenSSH : type + base64 + comment
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- FK composite vers le workspace propriétaire
    FOREIGN KEY (login, workspace_name) REFERENCES workspaces(login, name)
        ON DELETE CASCADE,
    UNIQUE (login, workspace_name)
);
```

> **Note migration** : la clé privée n'est jamais stockée en base. `private_key_path` pointe vers le fichier `0o600` sur le volume `/data`. En cas de migration vers un stockage chiffré, le binaire serait stocké dans une colonne `BYTEA` chiffrée (ex. `pg_crypto` + clé KEK).
