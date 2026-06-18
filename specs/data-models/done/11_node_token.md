# 11 — Tokens de jointure nœuds

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | Token hashé + métadonnées (node_name, address, expires_at, used) |
| Chemin | `/data/tokens/{sha256(token)}.json` |
| Fonction | `nodes/enroll.py :: _atomic_write_json()` |
| Format | JSON |
| Écriture | Atomique : tempfile + `os.replace()` |

Token jamais stocké en clair — seulement son SHA256. Usage unique, TTL 1h. Consommation atomique via `asyncio.Lock` par token.

---

## Modèle Python (Pydantic v2)

Pas de modèle Pydantic dédié — données brutes dict JSON. Modèle logique :

```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class NodeJoinToken(BaseModel):
    """Structure JSON persistée dans /data/tokens/{sha256}.json"""
    model_config = ConfigDict(extra="forbid")

    node_name:  str       # DNS-safe ^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$
    address:    str       # IP ou hostname du nœud
    expires_at: datetime  # UTC, TTL = 1h depuis génération
    used:       bool      # True après consommation — jamais supprimé avant expiration

# Fonctions associées dans nodes/enroll.py :
#
# def generate_token(node_name: str, address: str) -> str:
#     token = secrets.token_urlsafe(32)
#     data = { "node_name": ..., "address": ..., "expires_at": ..., "used": False }
#     _atomic_write_json(_token_path(token), data)   # stocke SHA256 comme nom de fichier
#     return token   # le token en clair est retourné UNE SEULE FOIS
#
# async def consume_token(token: str) -> tuple[str, str]:
#     async with _get_token_lock(token):
#         data = json.loads(_token_path(token).read_text())
#         assert not data["used"] and not expired
#         data["used"] = True
#         _atomic_write_json(...)
#     return (data["node_name"], data["address"])
```

---

## Tables SQL équivalentes

```sql
CREATE TABLE node_join_tokens (
    token_hash  TEXT PRIMARY KEY,     -- SHA256 hex du token en clair
    node_name   TEXT NOT NULL,        -- DNS-safe
    address     TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    used        BOOLEAN NOT NULL DEFAULT FALSE,
    used_at     TIMESTAMPTZ,          -- NULL tant que non consommé
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_node_join_tokens_expires ON node_join_tokens(expires_at)
    WHERE NOT used;
-- Permet un cleanup périodique des tokens expirés non utilisés.
```
