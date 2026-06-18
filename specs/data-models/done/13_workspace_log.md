# 13 — Logs workspaces

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | Stdout + stderr du subprocess devpod |
| Chemin | `/data/logs/{login}/{ws_id}.log` |
| Fonction | `devpod/runner.py :: run_subprocess()` |
| Format | Texte brut UTF-8 |
| Écriture | Streamée ligne par ligne, flush après chaque ligne |

Un fichier par workspace par opération (up, stop). Les logs sont lisibles en temps réel par l'UI via SSE ou polling. Pas d'expiration automatique.

---

## Modèle Python (Pydantic v2)

Pas de modèle Pydantic — flux texte brut. Modèle logique de l'entrée de log :

```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class WorkspaceLogEntry(BaseModel):
    """Représentation logique d'une ligne de log workspace."""
    model_config = ConfigDict(extra="forbid")

    ws_id:    str
    login:    str
    line:     str       # ligne brute stdout/stderr du subprocess devpod
    # En base, on pourrait ajouter :
    # logged_at: datetime
    # stream:    Literal["stdout", "stderr"]

# Extrait de runner.py :
# async def run_subprocess(cmd, env, log_path, ws_id):
#     log_path.parent.mkdir(parents=True, exist_ok=True)
#     with open(log_path, "w", encoding="utf-8") as f:
#         async for line in proc.stdout:
#             f.write(line.decode(errors="replace"))
#             f.flush()
```

---

## Tables SQL équivalentes

```sql
-- Option A : stocker les lignes individuellement (queryable, mais volume élevé)
CREATE TABLE workspace_logs (
    id          BIGSERIAL PRIMARY KEY,
    ws_id       TEXT NOT NULL,
    login       TEXT NOT NULL,
    stream      TEXT NOT NULL DEFAULT 'stdout',  -- 'stdout' | 'stderr'
    line        TEXT NOT NULL,
    logged_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_workspace_logs_ws_id ON workspace_logs(ws_id, logged_at);

-- Option B : stocker le log complet comme blob (plus simple, moins queryable)
CREATE TABLE workspace_log_blobs (
    id          SERIAL PRIMARY KEY,
    ws_id       TEXT NOT NULL,
    login       TEXT NOT NULL,
    operation   TEXT NOT NULL DEFAULT 'up',  -- 'up' | 'stop' | 'delete'
    content     TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    UNIQUE (ws_id, operation, started_at)
);

-- Recommandation : Option B pour la migration initiale.
-- Option A si l'UI doit permettre la recherche dans les logs.
```
