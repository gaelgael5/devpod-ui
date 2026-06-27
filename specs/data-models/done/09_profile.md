# 09 — Profiles

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | `Profile` (name, description, extensions VSCode, settings) |
| Chemin partagé | `/data/profiles/{slug}.yaml` |
| Chemin utilisateur | `/data/users/{login}/profiles/{slug}.yaml` |
| Fonction | `profiles/repository.py :: ProfileRepository._write()` via `_atomic_dump()` |
| Format | YAML |
| Écriture | Atomique : tempfile + `os.replace()` |

Slug auto-généré par `slugify()`, dédupliqué avec suffixe `-N` si collision. Un profil shared est visible par tous ; un profil user est privé. Un utilisateur peut "forker" un shared pour le personnaliser.

---

## Modèle Python (Pydantic v2)

```python
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

Scope = Literal["shared", "user"]

class ProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80, pattern=r"^[\w\s\-+.]{1,80}$")
    description: str = ""
    extensions: list[str] = Field(default_factory=list)   # IDs d'extensions VSCode
    settings: dict[str, Any] = Field(default_factory=dict) # settings VSCode JSON

class Profile(ProfileBody):
    slug: str   # ^[a-z0-9][a-z0-9-]{0,62}$
    scope: Scope

    def to_customizations(self) -> dict[str, Any]:
        """Format VSCode devcontainer customizations."""
        return {"vscode": {"extensions": self.extensions, "settings": self.settings}}

class ProfileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    scope: Scope
    name: str
    description: str
    extension_count: int
    editable: bool
```

---

## Tables SQL équivalentes

```sql
CREATE TABLE profiles (
    slug        TEXT NOT NULL,
    scope       TEXT NOT NULL,    -- 'shared' | 'user'
    login       TEXT REFERENCES users(login) ON DELETE CASCADE,  -- NULL si shared
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    extensions  TEXT[] NOT NULL DEFAULT '{}',
    settings    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (slug, scope, COALESCE(login, ''))
);

CREATE INDEX idx_profiles_login ON profiles(login) WHERE login IS NOT NULL;
CREATE INDEX idx_profiles_scope ON profiles(scope);
```
