# 03 — Contraintes SQL : ssh_workspace

Tables concernées : `workspace_ssh_keys`

```sql
-- ============================================================
-- TABLE : workspace_ssh_keys
-- ============================================================

ALTER TABLE workspace_ssh_keys
    ADD CONSTRAINT FK_workspace_ssh_keys_workspace
        FOREIGN KEY (login, workspace_name)
        REFERENCES workspaces(login, name)
        ON DELETE CASCADE;

ALTER TABLE workspace_ssh_keys
    ADD CONSTRAINT UQ_workspace_ssh_keys_login_workspace
        UNIQUE (login, workspace_name);

ALTER TABLE workspace_ssh_keys
    ADD CONSTRAINT CK_workspace_ssh_keys_private_key_path_nonempty
        CHECK (private_key_path <> '');

ALTER TABLE workspace_ssh_keys
    ADD CONSTRAINT CK_workspace_ssh_keys_public_key_nonempty
        CHECK (public_key <> '');

-- La clé publique doit commencer par un type SSH valide
ALTER TABLE workspace_ssh_keys
    ADD CONSTRAINT CK_workspace_ssh_keys_public_key_format
        CHECK (
            public_key LIKE 'ssh-ed25519 %'
            OR public_key LIKE 'ssh-rsa %'
            OR public_key LIKE 'ecdsa-sha2-%'
        );

-- Index
CREATE INDEX IF NOT EXISTS IX_workspace_ssh_keys_login
    ON workspace_ssh_keys(login);
```
