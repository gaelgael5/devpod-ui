# 13 — Contraintes SQL : workspace_log

Tables concernées : `workspace_logs` (option A), `workspace_log_blobs` (option B)

```sql
-- ============================================================
-- OPTION A — TABLE : workspace_logs (lignes individuelles)
-- ============================================================

ALTER TABLE workspace_logs
    ADD CONSTRAINT CK_workspace_logs_ws_id_nonempty
        CHECK (ws_id <> '');

ALTER TABLE workspace_logs
    ADD CONSTRAINT CK_workspace_logs_ws_id_dns
        CHECK (ws_id ~ '^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$');

ALTER TABLE workspace_logs
    ADD CONSTRAINT CK_workspace_logs_login_nonempty
        CHECK (login <> '');

ALTER TABLE workspace_logs
    ADD CONSTRAINT CK_workspace_logs_stream_values
        CHECK (stream IN ('stdout', 'stderr'));

ALTER TABLE workspace_logs
    ADD CONSTRAINT CK_workspace_logs_line_nonempty
        CHECK (line <> '');

ALTER TABLE workspace_logs
    ADD CONSTRAINT FK_workspace_logs_ws_id
        FOREIGN KEY (ws_id)
        REFERENCES workspace_status(ws_id)
        ON DELETE CASCADE;

-- Index
CREATE INDEX IF NOT EXISTS IX_workspace_logs_ws_id_logged_at
    ON workspace_logs(ws_id, logged_at DESC);

-- ============================================================
-- OPTION B — TABLE : workspace_log_blobs (blob complet)
-- ============================================================

ALTER TABLE workspace_log_blobs
    ADD CONSTRAINT UQ_workspace_log_blobs_ws_operation_started
        UNIQUE (ws_id, operation, started_at);

ALTER TABLE workspace_log_blobs
    ADD CONSTRAINT CK_workspace_log_blobs_ws_id_nonempty
        CHECK (ws_id <> '');

ALTER TABLE workspace_log_blobs
    ADD CONSTRAINT CK_workspace_log_blobs_ws_id_dns
        CHECK (ws_id ~ '^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$');

ALTER TABLE workspace_log_blobs
    ADD CONSTRAINT CK_workspace_log_blobs_login_nonempty
        CHECK (login <> '');

ALTER TABLE workspace_log_blobs
    ADD CONSTRAINT CK_workspace_log_blobs_operation_values
        CHECK (operation IN ('up', 'stop', 'delete'));

ALTER TABLE workspace_log_blobs
    ADD CONSTRAINT CK_workspace_log_blobs_finished_after_started
        CHECK (finished_at IS NULL OR finished_at >= started_at);

ALTER TABLE workspace_log_blobs
    ADD CONSTRAINT FK_workspace_log_blobs_ws_id
        FOREIGN KEY (ws_id)
        REFERENCES workspace_status(ws_id)
        ON DELETE CASCADE;

-- Index
CREATE INDEX IF NOT EXISTS IX_workspace_log_blobs_ws_id
    ON workspace_log_blobs(ws_id, started_at DESC);
```
