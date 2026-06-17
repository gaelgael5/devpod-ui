# 06 — Contraintes SQL : node_cert

Tables concernées : `node_certificates`

```sql
-- ============================================================
-- TABLE : node_certificates
-- ============================================================

ALTER TABLE node_certificates
    ADD CONSTRAINT FK_node_certificates_node_name
        FOREIGN KEY (node_name)
        REFERENCES hosts(name)
        ON DELETE CASCADE;

ALTER TABLE node_certificates
    ADD CONSTRAINT UQ_node_certificates_node_name
        UNIQUE (node_name);

ALTER TABLE node_certificates
    ADD CONSTRAINT CK_node_certificates_node_name_dns
        CHECK (node_name ~ '^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$');

ALTER TABLE node_certificates
    ADD CONSTRAINT CK_node_certificates_address_nonempty
        CHECK (address <> '');

ALTER TABLE node_certificates
    ADD CONSTRAINT CK_node_certificates_cert_pem_nonempty
        CHECK (cert_pem <> '');

ALTER TABLE node_certificates
    ADD CONSTRAINT CK_node_certificates_cert_pem_format
        CHECK (cert_pem LIKE '-----BEGIN CERTIFICATE-----%');

ALTER TABLE node_certificates
    ADD CONSTRAINT CK_node_certificates_expires_after_signed
        CHECK (expires_at > signed_at);

-- Un certificat révoqué ne peut pas être révoqué avant d'avoir été signé
ALTER TABLE node_certificates
    ADD CONSTRAINT CK_node_certificates_revoked_after_signed
        CHECK (revoked_at IS NULL OR revoked_at >= signed_at);

-- Index
CREATE INDEX IF NOT EXISTS IX_node_certificates_expires
    ON node_certificates(expires_at)
    WHERE revoked_at IS NULL;
```
