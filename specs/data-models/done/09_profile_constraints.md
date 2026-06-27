# 09 — Contraintes SQL : profile

Tables concernées : `profiles`

```sql
-- ============================================================
-- TABLE : profiles
-- ============================================================

ALTER TABLE profiles
    ADD CONSTRAINT CK_profiles_slug_pattern
        CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$');

ALTER TABLE profiles
    ADD CONSTRAINT CK_profiles_scope
        CHECK (scope IN ('shared', 'user'));

-- login NULL uniquement pour scope='shared'
ALTER TABLE profiles
    ADD CONSTRAINT CK_profiles_login_scope_consistency
        CHECK (
            (scope = 'shared' AND login IS NULL)
            OR (scope = 'user'   AND login IS NOT NULL)
        );

ALTER TABLE profiles
    ADD CONSTRAINT FK_profiles_login
        FOREIGN KEY (login)
        REFERENCES users(login)
        ON DELETE CASCADE;

ALTER TABLE profiles
    ADD CONSTRAINT CK_profiles_name_nonempty
        CHECK (name <> '');

ALTER TABLE profiles
    ADD CONSTRAINT CK_profiles_name_length
        CHECK (char_length(name) BETWEEN 1 AND 80);

ALTER TABLE profiles
    ADD CONSTRAINT CK_profiles_name_pattern
        CHECK (name ~ '^[\w\s\-+.]{1,80}$');

-- Index
CREATE INDEX IF NOT EXISTS IX_profiles_login
    ON profiles(login)
    WHERE login IS NOT NULL;

CREATE INDEX IF NOT EXISTS IX_profiles_scope
    ON profiles(scope);
```
