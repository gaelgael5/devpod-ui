# 02 — Contraintes SQL : user_config

Tables concernées : `users`, `git_credentials`, `workspaces`, `workspace_extra_sources`

```sql
-- ============================================================
-- TABLE : users
-- ============================================================

ALTER TABLE users
    ADD CONSTRAINT CK_users_login_pattern
        CHECK (login ~ '^[a-z0-9][a-z0-9._-]{0,38}[a-z0-9]$');

ALTER TABLE users
    ADD CONSTRAINT CK_users_login_nonempty
        CHECK (login <> '');

ALTER TABLE users
    ADD CONSTRAINT UQ_users_secret_ns
        UNIQUE (secret_ns);

ALTER TABLE users
    ADD CONSTRAINT CK_users_default_ide_nonempty
        CHECK (default_ide <> '');

-- ============================================================
-- TABLE : git_credentials
-- ============================================================

ALTER TABLE git_credentials
    ADD CONSTRAINT FK_git_credentials_login
        FOREIGN KEY (login)
        REFERENCES users(login)
        ON DELETE CASCADE;

ALTER TABLE git_credentials
    ADD CONSTRAINT UQ_git_credentials_login_name
        UNIQUE (login, name);

ALTER TABLE git_credentials
    ADD CONSTRAINT CK_git_credentials_kind
        CHECK (kind IN ('ssh', 'token'));

ALTER TABLE git_credentials
    ADD CONSTRAINT CK_git_credentials_name_nonempty
        CHECK (name <> '');

ALTER TABLE git_credentials
    ADD CONSTRAINT CK_git_credentials_host_nonempty
        CHECK (host <> '');

-- Pour kind='ssh' : key_path obligatoire
ALTER TABLE git_credentials
    ADD CONSTRAINT CK_git_credentials_ssh_fields
        CHECK (
            kind <> 'ssh'
            OR key_path <> ''
        );

-- Pour kind='token' : username obligatoire
ALTER TABLE git_credentials
    ADD CONSTRAINT CK_git_credentials_token_fields
        CHECK (
            kind <> 'token'
            OR username <> ''
        );

-- ============================================================
-- TABLE : workspaces
-- ============================================================

ALTER TABLE workspaces
    ADD CONSTRAINT FK_workspaces_login
        FOREIGN KEY (login)
        REFERENCES users(login)
        ON DELETE CASCADE;

ALTER TABLE workspaces
    ADD CONSTRAINT UQ_workspaces_login_name
        UNIQUE (login, name);

ALTER TABLE workspaces
    ADD CONSTRAINT CK_workspaces_name_dns
        CHECK (name ~ '^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$');

ALTER TABLE workspaces
    ADD CONSTRAINT CK_workspaces_source_nonempty
        CHECK (source <> '');

-- source ne doit pas commencer par '-' (injection d'argument CLI)
ALTER TABLE workspaces
    ADD CONSTRAINT CK_workspaces_source_no_dash_prefix
        CHECK (source NOT LIKE '-%');

-- profile_scope et profile_slug sont soit tous les deux NULL, soit tous les deux renseignés
ALTER TABLE workspaces
    ADD CONSTRAINT CK_workspaces_profile_consistency
        CHECK (
            (profile_scope IS NULL AND profile_slug IS NULL)
            OR (profile_scope IS NOT NULL AND profile_slug IS NOT NULL)
        );

ALTER TABLE workspaces
    ADD CONSTRAINT CK_workspaces_profile_scope
        CHECK (profile_scope IN ('shared', 'user') OR profile_scope IS NULL);

-- Index
CREATE INDEX IF NOT EXISTS IX_workspaces_login ON workspaces(login);

-- ============================================================
-- TABLE : workspace_extra_sources
-- ============================================================

ALTER TABLE workspace_extra_sources
    ADD CONSTRAINT FK_workspace_extra_sources_workspace
        FOREIGN KEY (workspace_id)
        REFERENCES workspaces(id)
        ON DELETE CASCADE;

ALTER TABLE workspace_extra_sources
    ADD CONSTRAINT CK_workspace_extra_sources_url_nonempty
        CHECK (url <> '');

ALTER TABLE workspace_extra_sources
    ADD CONSTRAINT CK_workspace_extra_sources_position_positive
        CHECK (position >= 0);

-- Index
CREATE INDEX IF NOT EXISTS IX_workspace_extra_sources_workspace_id
    ON workspace_extra_sources(workspace_id);
```
