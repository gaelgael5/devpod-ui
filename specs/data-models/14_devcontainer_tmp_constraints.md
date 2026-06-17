# 14 — Contraintes SQL : devcontainer_tmp

Tables concernées : `workspace_build_contexts` (table optionnelle d'observabilité)

```sql
-- ============================================================
-- TABLE : workspace_build_contexts  (optionnelle)
-- ============================================================

ALTER TABLE workspace_build_contexts
    ADD CONSTRAINT CK_workspace_build_contexts_ws_id_nonempty
        CHECK (ws_id <> '');

ALTER TABLE workspace_build_contexts
    ADD CONSTRAINT CK_workspace_build_contexts_ws_id_dns
        CHECK (ws_id ~ '^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$');

ALTER TABLE workspace_build_contexts
    ADD CONSTRAINT CK_workspace_build_contexts_login_nonempty
        CHECK (login <> '');

ALTER TABLE workspace_build_contexts
    ADD CONSTRAINT CK_workspace_build_contexts_dc_path_nonempty
        CHECK (dc_path <> '');

-- purged_at doit être postérieur à started_at
ALTER TABLE workspace_build_contexts
    ADD CONSTRAINT CK_workspace_build_contexts_purged_after_started
        CHECK (purged_at IS NULL OR purged_at >= started_at);

ALTER TABLE workspace_build_contexts
    ADD CONSTRAINT FK_workspace_build_contexts_ws_id
        FOREIGN KEY (ws_id)
        REFERENCES workspace_status(ws_id)
        ON DELETE CASCADE;

-- Index
CREATE INDEX IF NOT EXISTS IX_workspace_build_contexts_ws_id
    ON workspace_build_contexts(ws_id, started_at DESC);

CREATE INDEX IF NOT EXISTS IX_workspace_build_contexts_not_purged
    ON workspace_build_contexts(started_at)
    WHERE purged_at IS NULL;
```
