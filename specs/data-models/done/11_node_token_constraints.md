# 11 — Contraintes SQL : node_token

Tables concernées : `node_join_tokens`

```sql
-- ============================================================
-- TABLE : node_join_tokens
-- ============================================================

ALTER TABLE node_join_tokens
    ADD CONSTRAINT CK_node_join_tokens_token_hash_nonempty
        CHECK (token_hash <> '');

-- SHA256 hex = 64 caractères hexadécimaux
ALTER TABLE node_join_tokens
    ADD CONSTRAINT CK_node_join_tokens_token_hash_format
        CHECK (token_hash ~ '^[0-9a-f]{64}$');

ALTER TABLE node_join_tokens
    ADD CONSTRAINT CK_node_join_tokens_node_name_dns
        CHECK (node_name ~ '^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$');

ALTER TABLE node_join_tokens
    ADD CONSTRAINT CK_node_join_tokens_address_nonempty
        CHECK (address <> '');

ALTER TABLE node_join_tokens
    ADD CONSTRAINT CK_node_join_tokens_expires_after_created
        CHECK (expires_at > created_at);

-- TTL maximum cohérent avec _TOKEN_TTL_SECONDS = 3600s
ALTER TABLE node_join_tokens
    ADD CONSTRAINT CK_node_join_tokens_ttl_max_1h
        CHECK (expires_at <= created_at + INTERVAL '1 hour 1 minute');

-- used_at ne peut être renseigné que si used = TRUE
ALTER TABLE node_join_tokens
    ADD CONSTRAINT CK_node_join_tokens_used_at_consistency
        CHECK (
            (used = FALSE AND used_at IS NULL)
            OR (used = TRUE)
        );

-- used_at doit être postérieur à created_at
ALTER TABLE node_join_tokens
    ADD CONSTRAINT CK_node_join_tokens_used_at_after_created
        CHECK (used_at IS NULL OR used_at >= created_at);

-- Index
CREATE INDEX IF NOT EXISTS IX_node_join_tokens_expires
    ON node_join_tokens(expires_at)
    WHERE used = FALSE;
```
