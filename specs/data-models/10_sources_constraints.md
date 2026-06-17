# 10 — Contraintes SQL : sources

Tables concernées : `recipe_sources`, `profile_sources`

```sql
-- ============================================================
-- TABLE : recipe_sources
-- ============================================================

ALTER TABLE recipe_sources
    ADD CONSTRAINT UQ_recipe_sources_url
        UNIQUE (url);

ALTER TABLE recipe_sources
    ADD CONSTRAINT CK_recipe_sources_url_https
        CHECK (url LIKE 'https://%');

ALTER TABLE recipe_sources
    ADD CONSTRAINT CK_recipe_sources_url_nonempty
        CHECK (url <> '');

ALTER TABLE recipe_sources
    ADD CONSTRAINT CK_recipe_sources_position_positive
        CHECK (position >= 0);

-- Index pour l'ordre d'affichage
CREATE INDEX IF NOT EXISTS IX_recipe_sources_position
    ON recipe_sources(position)
    WHERE enabled = TRUE;

-- ============================================================
-- TABLE : profile_sources
-- ============================================================

ALTER TABLE profile_sources
    ADD CONSTRAINT UQ_profile_sources_url
        UNIQUE (url);

ALTER TABLE profile_sources
    ADD CONSTRAINT CK_profile_sources_url_https
        CHECK (url LIKE 'https://%');

ALTER TABLE profile_sources
    ADD CONSTRAINT CK_profile_sources_url_nonempty
        CHECK (url <> '');

ALTER TABLE profile_sources
    ADD CONSTRAINT CK_profile_sources_position_positive
        CHECK (position >= 0);

-- Index pour l'ordre d'affichage
CREATE INDEX IF NOT EXISTS IX_profile_sources_position
    ON profile_sources(position)
    WHERE enabled = TRUE;
```
