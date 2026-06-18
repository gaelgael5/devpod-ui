# 05 — Contraintes SQL : ssh_host

Tables concernées : `hosts` (colonnes `key_path` et `public_key` — définies dans `01_global_config`)

Les contraintes principales sur `hosts` sont dans `01_global_config_constraints`.
Ce fichier documente les contraintes spécifiques aux colonnes SSH de la clé hôte.

```sql
-- ============================================================
-- Contraintes SSH sur hosts (type = 'ssh')
-- Complément de 01_global_config_constraints
-- ============================================================

-- Cohérence key_path / public_key pour les hosts SSH :
-- si l'un est renseigné, l'autre doit l'être aussi.
ALTER TABLE hosts
    ADD CONSTRAINT CK_hosts_ssh_key_pair_consistency
        CHECK (
            type <> 'ssh'
            OR (
                (key_path = '' AND public_key = '')
                OR (key_path <> '' AND public_key <> '')
            )
        );

-- La clé publique SSH doit commencer par un type valide (quand renseignée)
ALTER TABLE hosts
    ADD CONSTRAINT CK_hosts_public_key_format
        CHECK (
            public_key = ''
            OR public_key LIKE 'ssh-ed25519 %'
            OR public_key LIKE 'ssh-rsa %'
            OR public_key LIKE 'ecdsa-sha2-%'
        );

-- key_path ne doit pas être renseigné pour un host docker-tls
ALTER TABLE hosts
    ADD CONSTRAINT CK_hosts_no_key_path_for_docker_tls
        CHECK (
            type <> 'docker-tls'
            OR key_path = ''
        );
```
