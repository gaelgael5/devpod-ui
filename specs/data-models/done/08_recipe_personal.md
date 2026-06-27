# 08 — Recipes personnelles (start recipes)

## Description

| Champ | Valeur |
|-------|--------|
| Modèle | `RecipeMeta` (type=start) + script |
| Chemin | `/data/users/{login}/recipes/{recipe_id}/recipe.meta.yaml` + `start.sh` |
| Fonction | `routes/recipes.py :: create_personal_start_recipe()` |
| Format | YAML + Shell (`start.sh` chmod `0o755`) |
| Écriture | mkdir(tmp) + write_text + rename |

Recipes de démarrage créées par un utilisateur. Type forcé à `start` (pas de `devcontainer-feature.json`, pas de `install.sh`). Visibles uniquement par leur propriétaire.

---

## Modèle Python (Pydantic v2)

Même modèle `RecipeMeta` que les recipes partagées (voir `07_recipe_shared`), avec les contraintes suivantes :

```python
# Création côté route — vérifications supplémentaires appliquées par la route
class PersonalStartRecipeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str           # ^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$
    description: str = ""
    start_sh: str     # contenu du script start.sh (doit commencer par #!/usr/bin/env bash)

# RecipeMeta résultante
# type = "start"  (forcé)
# scope = "user"  (implicite)
# key  = UUID auto-généré
```

---

## Tables SQL équivalentes

```sql
-- Pas de table séparée : même table `recipes` que 07_recipe_shared,
-- avec scope='user' et login renseigné.

-- Rappel du discriminant :
--   scope = 'shared'  → recette admin, login = NULL
--   scope = 'builtin' → recette embarquée dans l'image, login = NULL
--   scope = 'user'    → recette personnelle, login = <login utilisateur>
--   type  = 'start'   → pas de feature_json, pas d'install_sh
--            install_sh = NULL, feature_json = NULL, start_sh = <contenu>

-- Index utile pour lister les recipes visibles par un utilisateur :
CREATE INDEX idx_recipes_login ON recipes(login) WHERE login IS NOT NULL;
CREATE INDEX idx_recipes_scope ON recipes(scope);
```
