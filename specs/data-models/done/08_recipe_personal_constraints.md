# 08 — Contraintes SQL : recipe_personal

Tables concernées : `recipes` (scope = 'user') — définies dans `07_recipe_shared`

Pas de table supplémentaire. Les contraintes du scope 'user' sont un sous-ensemble
des contraintes de `07_recipe_shared_constraints`. Ce fichier documente les
contraintes et index spécifiques aux recipes personnelles.

```sql
-- ============================================================
-- Contraintes spécifiques scope='user' sur la table recipes
-- Complément de 07_recipe_shared_constraints
-- ============================================================

-- Une recipe personnelle de type 'start' ne peut pas avoir de feature_json
-- (déjà couvert par CK_recipes_start_no_install_artifacts dans 07)

-- Un utilisateur ne peut pas avoir deux recipes personnelles avec le même id
ALTER TABLE recipes
    ADD CONSTRAINT UQ_recipes_user_id_login
        UNIQUE (id, login)
        -- Applicable uniquement pour scope='user' ; la contrainte de PK composite
        -- (id, scope, COALESCE(login, '')) couvre déjà ce cas.
        -- Cet index dédié améliore les lookups par (login, id).
        DEFERRABLE INITIALLY IMMEDIATE;

-- Index pour lister toutes les recipes visibles par un utilisateur :
-- shared/builtin + ses recipes personnelles
CREATE INDEX IF NOT EXISTS IX_recipes_visible_for_user
    ON recipes(login, scope, type);
```
