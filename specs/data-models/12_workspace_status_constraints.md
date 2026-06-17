# 12 — Contraintes SQL : workspace_status

Tables concernées : `workspace_status`

```sql
-- ============================================================
-- TABLE : workspace_status
-- ============================================================

ALTER TABLE workspace_status
    ADD CONSTRAINT FK_workspace_status_login
        FOREIGN KEY (login)
        REFERENCES users(login)
        ON DELETE SET DEFAULT
        DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE workspace_status
    ADD CONSTRAINT CK_workspace_status_ws_id_nonempty
        CHECK (ws_id <> '');

-- ws_id = '{login}-{name}' → DNS-safe
ALTER TABLE workspace_status
    ADD CONSTRAINT CK_workspace_status_ws_id_dns
        CHECK (ws_id ~ '^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$');

ALTER TABLE workspace_status
    ADD CONSTRAINT CK_workspace_status_status_values
        CHECK (status IN ('provisioning', 'running', 'stopped', 'failed', 'unknown'));

ALTER TABLE workspace_status
    ADD CONSTRAINT CK_workspace_status_host_type
        CHECK (host_type IS NULL OR host_type IN ('docker-tls', 'ssh'));

-- host_port dans la plage DevPod (40000–49999 selon exposure/ports.py)
ALTER TABLE workspace_status
    ADD CONSTRAINT CK_workspace_status_host_port_range
        CHECK (host_port IS NULL OR (host_port >= 40000 AND host_port <= 49999));

-- url présente uniquement si status = 'running'
ALTER TABLE workspace_status
    ADD CONSTRAINT CK_workspace_status_url_running_only
        CHECK (
            url IS NULL
            OR status = 'running'
        );

-- hostname présent uniquement si status = 'running'
ALTER TABLE workspace_status
    ADD CONSTRAINT CK_workspace_status_hostname_running_only
        CHECK (
            hostname IS NULL
            OR status = 'running'
        );

-- error présent uniquement si status IN ('failed', 'unknown')
ALTER TABLE workspace_status
    ADD CONSTRAINT CK_workspace_status_error_failed_only
        CHECK (
            error IS NULL
            OR status IN ('failed', 'unknown')
        );

-- returncode 0 attendu uniquement si running
ALTER TABLE workspace_status
    ADD CONSTRAINT CK_workspace_status_returncode_failed
        CHECK (
            returncode IS NULL
            OR status IN ('running', 'stopped', 'failed', 'unknown')
        );

-- Index
CREATE INDEX IF NOT EXISTS IX_workspace_status_login
    ON workspace_status(login);

CREATE INDEX IF NOT EXISTS IX_workspace_status_status
    ON workspace_status(status);
```
