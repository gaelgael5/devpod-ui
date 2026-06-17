# 07 — Recipes partagées (admin)

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | `RecipeMeta` + scripts |
| Chemin | `/data/recipes/{recipe_id}/recipe.meta.yaml` + `install.sh` + `devcontainer-feature.json` |
| Fonction | `routes/recipes.py :: admin_create_shared_recipe()` |
| Format | YAML + Shell + JSON |
| Écriture | Atomique par fichier : tempfile + `os.replace()` |

Recipes disponibles à tous les utilisateurs. `key` UUID stable (immuable après création). `installs_after` contient des GUIDs pointant vers d'autres recipes.

---

## Modèle Python (Pydantic v2)

```python
from __future__ import annotations
import re, uuid
from pathlib import Path
from typing import Any, Literal
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_RECIPE_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")
_SECRET_PATH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,127}$")
_ENV_VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

class RecipeOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = "string"
    default: str = ""
    description: str = ""

class SecretRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str   # ^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,127}$
    env: str    # ^[A-Z][A-Z0-9_]{0,63}$

class RecipeMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str                                    # ^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$
    key: str = Field(default_factory=lambda: str(uuid.uuid4()))  # UUID stable
    type: Literal["install", "start"] = "install"
    version: str = "1.0.0"
    description: str = ""
    options: dict[str, RecipeOption] = Field(default_factory=dict)
    requires_secrets: list[SecretRef] = Field(default_factory=list)
    installs_after: list[str] = Field(default_factory=list)  # GUIDs (key) des prérequis

    @classmethod
    def from_yaml(cls, path: str | Path) -> RecipeMeta:
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)
```

---

## Tables SQL équivalentes

```sql
CREATE TABLE recipes (
    id          TEXT NOT NULL,
    key         UUID NOT NULL UNIQUE,     -- identifiant stable immuable
    scope       TEXT NOT NULL DEFAULT 'shared',  -- 'shared' | 'builtin' | 'user'
    login       TEXT REFERENCES users(login) ON DELETE CASCADE,  -- NULL si shared
    type        TEXT NOT NULL DEFAULT 'install',  -- 'install' | 'start'
    version     TEXT NOT NULL DEFAULT '1.0.0',
    description TEXT NOT NULL DEFAULT '',
    -- Contenu des scripts (alternative à stocker le chemin filesystem)
    install_sh  TEXT,   -- contenu de install.sh  (type=install)
    start_sh    TEXT,   -- contenu de start.sh    (type=start)
    feature_json JSONB, -- contenu de devcontainer-feature.json (type=install)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, scope, COALESCE(login, ''))
);

CREATE TABLE recipe_options (
    id          SERIAL PRIMARY KEY,
    recipe_key  UUID NOT NULL REFERENCES recipes(key) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'string',
    default_val TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    UNIQUE (recipe_key, name)
);

CREATE TABLE recipe_secret_refs (
    id          SERIAL PRIMARY KEY,
    recipe_key  UUID NOT NULL REFERENCES recipes(key) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    env_var     TEXT NOT NULL
);

-- Dépendances : recipe_key → dépend de → depends_on_key
CREATE TABLE recipe_dependencies (
    recipe_key      UUID NOT NULL REFERENCES recipes(key) ON DELETE CASCADE,
    depends_on_key  UUID NOT NULL REFERENCES recipes(key) ON DELETE RESTRICT,
    position        INTEGER NOT NULL DEFAULT 0,  -- ordre de déclaration
    PRIMARY KEY (recipe_key, depends_on_key)
);
```
