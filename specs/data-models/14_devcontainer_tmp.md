# 14 — devcontainer.json temporaires

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | devcontainer.json généré + copies des features recipes |
| Chemin | `/data/users/{login}/devpod/{ws_id}-dc-{rand}/devcontainer.json` |
| Fonction | `devpod/service.py :: _write_devcontainer()` |
| Format | JSON + Shell (copies recipes) |
| Écriture | `tempfile.mkdtemp()` + write_text + `shutil.copytree()` |

Artefact **éphémère** : créé juste avant `devpod up --devcontainer-path`, supprimé en bloc `finally` via `shutil.rmtree()` dès que DevPod a lu le fichier. Aucune valeur après l'opération.

---

## Modèle Python (Pydantic v2)

Pas de modèle Pydantic dédié. Structure JSON générée dynamiquement :

```python
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict

class DevcontainerJson(BaseModel):
    """Structure du devcontainer.json généré pour devpod up."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    image: str | None = None
    build: dict[str, Any] | None = None
    features: dict[str, Any] = {}          # { "path/to/feature": { options } }
    postCreateCommand: str = ""
    remoteEnv: dict[str, str] = {}
    customizations: dict[str, Any] = {}    # VSCode extensions + settings

# Généré dans _write_devcontainer() :
# dc = {
#     "image": image_or_none,
#     "features": { recipe_dir: options, ... },  # pour chaque recipe sélectionnée
#     "postCreateCommand": " && ".join(post_create_cmds),
#     "remoteEnv": { **workspace_env },
#     "customizations": profile.to_customizations() if profile else {},
# }
# Path(dc_dir / "devcontainer.json").write_text(json.dumps(dc, indent=2))
```

---

## Tables SQL équivalentes

```sql
-- Cet artefact est éphémère : il n'a pas besoin de persistance durable.
-- On peut toutefois tracer le contexte de build pour observabilité :

CREATE TABLE workspace_build_contexts (
    id          SERIAL PRIMARY KEY,
    ws_id       TEXT NOT NULL,
    login       TEXT NOT NULL,
    dc_path     TEXT NOT NULL,     -- chemin tmpdir (informatif, peut avoir disparu)
    recipes     TEXT[] NOT NULL DEFAULT '{}',
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    purged_at   TIMESTAMPTZ        -- NULL tant que le tmpdir existe
);

-- Cette table est optionnelle. En pratique, le ws_id suffit pour retrouver
-- le contexte via workspace_status + workspace_logs.
```
