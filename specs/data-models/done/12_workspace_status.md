# 12 — Statut workspaces + routes Caddy

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | `WorkspaceStatus` (ws_id, status, login, url, hostname, host_port, …) |
| Chemin | `/data/routes/{ws_id}.json` |
| Fonction | `devpod/service.py :: _write_status()`, `exposure/__init__.py :: _write_exposure()` |
| Format | JSON |
| Écriture | Atomique : tempfile + `os.replace()` |

Un fichier par workspace actif. Double rôle : état du cycle de vie DevPod + coordonnées de la route Caddy. Supprimé lors de `devpod delete`. Relu au redémarrage du portal pour réconcilier les port-forwards.

---

## Modèle Python (Pydantic v2)

Pas de modèle Pydantic dédié — dict JSON avec champs dynamiques. Modèle logique :

```python
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict

WorkspaceStatus = Literal[
    "provisioning", "running", "stopped", "failed", "unknown"
]

class WorkspaceStatusRecord(BaseModel):
    """Structure JSON persistée dans /data/routes/{ws_id}.json"""
    model_config = ConfigDict(extra="allow")  # champs dynamiques selon le statut

    ws_id:      str
    status:     WorkspaceStatus
    login:      str = ""
    # champs présents uniquement à l'état 'running'
    host_port:  int | None = None
    host_type:  str | None = None   # 'docker-tls' | 'ssh'
    host_name:  str | None = None
    url:        str | None = None   # URL publique via Caddy
    hostname:   str | None = None   # hostname DNS route Caddy
    # champs présents en cas d'échec
    returncode: int | None = None
    error:      str | None = None

# _write_status() construit data = {"ws_id": ..., "status": ..., **extra}
# _write_exposure() merge hostname + url dans le fichier existant
```

---

## Tables SQL équivalentes

```sql
CREATE TABLE workspace_status (
    ws_id       TEXT PRIMARY KEY,   -- format : '{login}-{name}'
    status      TEXT NOT NULL,      -- 'provisioning' | 'running' | 'stopped' | 'failed' | 'unknown'
    login       TEXT NOT NULL DEFAULT '',
    host_port   INTEGER,
    host_type   TEXT,               -- 'docker-tls' | 'ssh'
    host_name   TEXT,
    url         TEXT,               -- URL publique
    hostname    TEXT,               -- hostname DNS Caddy
    returncode  INTEGER,
    error       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_workspace_status_login ON workspace_status(login);
CREATE INDEX idx_workspace_status_status ON workspace_status(status);
```
