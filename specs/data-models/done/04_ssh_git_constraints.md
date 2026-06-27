# 04 — Contraintes SQL : ssh_git

Tables concernées : `git_credentials` (colonnes `key_path` et `public_key` — définies dans `02_user_config`)

Les contraintes sur `git_credentials` sont centralisées dans `02_user_config_constraints`.
Ce fichier documente les contraintes spécifiques aux colonnes SSH.

```sql
-- ============================================================
-- Contraintes SSH sur git_credentials (kind = 'ssh')
-- Complément de 02_user_config_constraints
-- ============================================================

-- Cohérence clé privée / clé publique pour kind='ssh' :
-- si key_path est renseigné, public_key doit l'être aussi et inversement.
ALTER TABLE git_credentials
    ADD CONSTRAINT CK_git_credentials_ssh_key_pair_consistency
        CHECK (
            kind <> 'ssh'
            OR (
                (key_path = '' AND public_key = '')
                OR (key_path <> '' AND public_key <> '')
            )
        );

-- La clé publique SSH doit commencer par un type valide (quand renseignée)
ALTER TABLE git_credentials
    ADD CONSTRAINT CK_git_credentials_public_key_format
        CHECK (
            public_key = ''
            OR public_key LIKE 'ssh-ed25519 %'
            OR public_key LIKE 'ssh-rsa %'
            OR public_key LIKE 'ecdsa-sha2-%'
        );

-- Index utile pour retrouver rapidement les credentials SSH d'un utilisateur
CREATE INDEX IF NOT EXISTS IX_git_credentials_login_kind
    ON git_credentials(login, kind);
```
