# 01 — Contraintes SQL : global_config

Tables concernées : `global_config`, `hosts`, `hypervisor_types`, `hypervisors`

```sql
-- ============================================================
-- TABLE : global_config
-- ============================================================

ALTER TABLE global_config
    ADD CONSTRAINT CK_global_config_singleton
        CHECK (id = 1);

ALTER TABLE global_config
    ADD CONSTRAINT CK_global_config_log_level
        CHECK (log_level IN ('debug', 'info', 'warning', 'error'));

ALTER TABLE global_config
    ADD CONSTRAINT CK_global_config_log_format
        CHECK (log_format IN ('text', 'json'));

ALTER TABLE global_config
    ADD CONSTRAINT CK_global_config_secrets_backend
        CHECK (secrets_backend IN ('harpocrate', 'inline'));

ALTER TABLE global_config
    ADD CONSTRAINT CK_global_config_base_domain_nonempty
        CHECK (base_domain <> '');

ALTER TABLE global_config
    ADD CONSTRAINT CK_global_config_external_url_nonempty
        CHECK (external_url <> '');

ALTER TABLE global_config
    ADD CONSTRAINT CK_global_config_oidc_issuer_nonempty
        CHECK (oidc_issuer <> '');

ALTER TABLE global_config
    ADD CONSTRAINT CK_global_config_oidc_client_id_nonempty
        CHECK (oidc_client_id <> '');

-- ============================================================
-- TABLE : hypervisor_types
-- (doit être créée avant hypervisors et hosts pour les FK)
-- ============================================================

ALTER TABLE hypervisor_types
    ADD CONSTRAINT UQ_hypervisor_types_name
        UNIQUE (name);

ALTER TABLE hypervisor_types
    ADD CONSTRAINT CK_hypervisor_types_name_dns
        CHECK (name ~ '^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$');

-- ============================================================
-- TABLE : hypervisors
-- ============================================================

ALTER TABLE hypervisors
    ADD CONSTRAINT UQ_hypervisors_name
        UNIQUE (name);

ALTER TABLE hypervisors
    ADD CONSTRAINT CK_hypervisors_name_dns
        CHECK (name ~ '^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$');

ALTER TABLE hypervisors
    ADD CONSTRAINT CK_hypervisors_address_nonempty
        CHECK (address <> '');

ALTER TABLE hypervisors
    ADD CONSTRAINT CK_hypervisors_ssh_port_range
        CHECK (ssh_port > 0 AND ssh_port <= 65535);

ALTER TABLE hypervisors
    ADD CONSTRAINT CK_hypervisors_ssh_key_path_nonempty
        CHECK (ssh_key_path <> '');

ALTER TABLE hypervisors
    ADD CONSTRAINT FK_hypervisors_hypervisor_type
        FOREIGN KEY (hypervisor_type)
        REFERENCES hypervisor_types(name)
        ON DELETE SET DEFAULT;

-- ============================================================
-- TABLE : hosts
-- ============================================================

ALTER TABLE hosts
    ADD CONSTRAINT UQ_hosts_name
        UNIQUE (name);

ALTER TABLE hosts
    ADD CONSTRAINT CK_hosts_name_dns
        CHECK (name ~ '^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$');

ALTER TABLE hosts
    ADD CONSTRAINT CK_hosts_type
        CHECK (type IN ('docker-tls', 'ssh'));

-- docker_host requis pour docker-tls, address + key_path requis pour ssh
ALTER TABLE hosts
    ADD CONSTRAINT CK_hosts_docker_tls_fields
        CHECK (
            type <> 'docker-tls'
            OR docker_host <> ''
        );

ALTER TABLE hosts
    ADD CONSTRAINT CK_hosts_ssh_fields
        CHECK (
            type <> 'ssh'
            OR (address <> '' AND key_path <> '')
        );

ALTER TABLE hosts
    ADD CONSTRAINT FK_hosts_proxmox_node
        FOREIGN KEY (proxmox_node)
        REFERENCES hypervisors(name)
        ON DELETE SET DEFAULT
        DEFERRABLE INITIALLY DEFERRED;

-- Index
CREATE INDEX IF NOT EXISTS IX_hosts_type ON hosts(type);
CREATE INDEX IF NOT EXISTS IX_hosts_is_default ON hosts(is_default) WHERE is_default = TRUE;
```
