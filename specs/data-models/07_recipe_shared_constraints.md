# 07 — Contraintes SQL : recipe_shared

Tables concernées : `recipes`, `recipe_options`, `recipe_secret_refs`, `recipe_dependencies`

```sql
-- ============================================================
-- TABLE : recipes
-- ============================================================

ALTER TABLE recipes
    ADD CONSTRAINT UQ_recipes_key
        UNIQUE (key);

ALTER TABLE recipes
    ADD CONSTRAINT CK_recipes_id_pattern
        CHECK (id ~ '^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$');

ALTER TABLE recipes
    ADD CONSTRAINT CK_recipes_id_nonempty
        CHECK (id <> '');

ALTER TABLE recipes
    ADD CONSTRAINT CK_recipes_scope
        CHECK (scope IN ('shared', 'builtin', 'user'));

ALTER TABLE recipes
    ADD CONSTRAINT CK_recipes_type
        CHECK (type IN ('install', 'start'));

ALTER TABLE recipes
    ADD CONSTRAINT CK_recipes_version_nonempty
        CHECK (version <> '');

-- login NULL uniquement pour scope shared ou builtin
ALTER TABLE recipes
    ADD CONSTRAINT CK_recipes_login_scope_consistency
        CHECK (
            (scope IN ('shared', 'builtin') AND login IS NULL)
            OR (scope = 'user' AND login IS NOT NULL)
        );

-- Pour type='install' : install_sh ou feature_json requis
ALTER TABLE recipes
    ADD CONSTRAINT CK_recipes_install_has_script
        CHECK (
            type <> 'install'
            OR (install_sh IS NOT NULL AND install_sh <> '')
        );

-- Pour type='start' : start_sh requis, install_sh et feature_json interdits
ALTER TABLE recipes
    ADD CONSTRAINT CK_recipes_start_has_script
        CHECK (
            type <> 'start'
            OR (start_sh IS NOT NULL AND start_sh <> '')
        );

ALTER TABLE recipes
    ADD CONSTRAINT CK_recipes_start_no_install_artifacts
        CHECK (
            type <> 'start'
            OR (install_sh IS NULL AND feature_json IS NULL)
        );

ALTER TABLE recipes
    ADD CONSTRAINT FK_recipes_login
        FOREIGN KEY (login)
        REFERENCES users(login)
        ON DELETE CASCADE;

-- Index
CREATE INDEX IF NOT EXISTS IX_recipes_scope ON recipes(scope);
CREATE INDEX IF NOT EXISTS IX_recipes_login ON recipes(login) WHERE login IS NOT NULL;
CREATE INDEX IF NOT EXISTS IX_recipes_type  ON recipes(type);

-- ============================================================
-- TABLE : recipe_options
-- ============================================================

ALTER TABLE recipe_options
    ADD CONSTRAINT FK_recipe_options_recipe_key
        FOREIGN KEY (recipe_key)
        REFERENCES recipes(key)
        ON DELETE CASCADE;

ALTER TABLE recipe_options
    ADD CONSTRAINT UQ_recipe_options_recipe_key_name
        UNIQUE (recipe_key, name);

ALTER TABLE recipe_options
    ADD CONSTRAINT CK_recipe_options_name_nonempty
        CHECK (name <> '');

ALTER TABLE recipe_options
    ADD CONSTRAINT CK_recipe_options_name_pattern
        CHECK (name ~ '^[A-Z][A-Z0-9_]{0,63}$'   -- variable d'env
               OR name ~ '^[a-z][a-zA-Z0-9_]{0,63}$');  -- camelCase/snake_case

ALTER TABLE recipe_options
    ADD CONSTRAINT CK_recipe_options_type_nonempty
        CHECK (type <> '');

-- ============================================================
-- TABLE : recipe_secret_refs
-- ============================================================

ALTER TABLE recipe_secret_refs
    ADD CONSTRAINT FK_recipe_secret_refs_recipe_key
        FOREIGN KEY (recipe_key)
        REFERENCES recipes(key)
        ON DELETE CASCADE;

ALTER TABLE recipe_secret_refs
    ADD CONSTRAINT CK_recipe_secret_refs_path_pattern
        CHECK (path ~ '^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,127}$');

ALTER TABLE recipe_secret_refs
    ADD CONSTRAINT CK_recipe_secret_refs_env_var_pattern
        CHECK (env_var ~ '^[A-Z][A-Z0-9_]{0,63}$');

-- Une même recette ne peut pas référencer deux fois le même env_var
ALTER TABLE recipe_secret_refs
    ADD CONSTRAINT UQ_recipe_secret_refs_recipe_env
        UNIQUE (recipe_key, env_var);

-- ============================================================
-- TABLE : recipe_dependencies
-- ============================================================

ALTER TABLE recipe_dependencies
    ADD CONSTRAINT FK_recipe_dependencies_recipe_key
        FOREIGN KEY (recipe_key)
        REFERENCES recipes(key)
        ON DELETE CASCADE;

ALTER TABLE recipe_dependencies
    ADD CONSTRAINT FK_recipe_dependencies_depends_on_key
        FOREIGN KEY (depends_on_key)
        REFERENCES recipes(key)
        ON DELETE RESTRICT;

ALTER TABLE recipe_dependencies
    ADD CONSTRAINT CK_recipe_dependencies_no_self_reference
        CHECK (recipe_key <> depends_on_key);

ALTER TABLE recipe_dependencies
    ADD CONSTRAINT CK_recipe_dependencies_position_positive
        CHECK (position >= 0);

-- Index
CREATE INDEX IF NOT EXISTS IX_recipe_dependencies_depends_on
    ON recipe_dependencies(depends_on_key);
```
