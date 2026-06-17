# 10 — Sources distantes

## Description

### Recipe sources

| Champ | Valeur |
|-------|--------|
| Modèle | Liste d'URLs |
| Chemin | `/data/recipe-sources.yaml` |
| Fonction | `routes/recipe_sources.py :: _save_sources()` |
| Format | YAML — `sources: [url, ...]` |
| Écriture | Atomique : tempfile + `os.replace()` |

### Profile sources

| Champ | Valeur |
|-------|--------|
| Modèle | Liste d'URLs |
| Chemin | `/data/profile-sources.yaml` |
| Fonction | `routes/profile_sources.py :: _save_sources()` |
| Format | YAML — `sources: [url, ...]` |
| Écriture | Atomique : tempfile + `os.replace()` |

URLs de catalogues externes (toc.txt). Seuls les admins peuvent les modifier. Validation SSRF stricte à l'écriture.

---

## Modèle Python (Pydantic v2)

```python
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, field_validator

class RecipeSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[str]   # URLs HTTPS validées anti-SSRF

class ProfileSourcesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[str]   # URLs HTTPS validées anti-SSRF

# Format sur disque (YAML) :
# sources:
#   - https://raw.githubusercontent.com/.../toc.txt

# Valeur par défaut recipe sources :
_DEFAULT_RECIPE_SOURCE = (
    "https://raw.githubusercontent.com/gaelgael5/devpod-ui/dev/recipes/toc.txt"
)
# Valeur par défaut profile sources :
_DEFAULT_PROFILE_SOURCE = (
    "https://raw.githubusercontent.com/gaelgael5/devpod-ui/dev/profiles/"
)
```

---

## Tables SQL équivalentes

```sql
CREATE TABLE recipe_sources (
    id          SERIAL PRIMARY KEY,
    url         TEXT NOT NULL UNIQUE,
    position    INTEGER NOT NULL DEFAULT 0,  -- ordre d'affichage / priorité
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE profile_sources (
    id          SERIAL PRIMARY KEY,
    url         TEXT NOT NULL UNIQUE,
    position    INTEGER NOT NULL DEFAULT 0,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
