# 035 — Écriture `.env` en read-modify-write sans verrou

- **Sévérité** : mineur (admin-only, rare ; écriture atomique et perms OK par ailleurs)
- **Sous-système** : config
- **Fichier** : `config/env_file.py:10-45` (appelé par `routes/admin.py:307`)
- **Statut** : corrigé — `update_env_file` est désormais `async`, sérialisée par un `asyncio.Lock`
  module-level qui couvre tout le cycle lecture→modification→écriture (un seul fichier `.env` par
  portail, un verrou global suffit). L'I/O bloquante (`_update_env_file_sync`) est déportée via
  `asyncio.to_thread`, corrigeant au passage la violation « jamais d'I/O bloquant dans un handler »
  (l'unique appelant, `routes/admin.py::put_admin_grafana_oidc`, l'appelait jusque-là de façon
  synchrone). Tests ajoutés : deux mises à jour concurrentes de clés distinctes ne se perdent plus
  (`asyncio.gather`), et un test d'ordre (spy sur `_update_env_file_sync`) prouve la sérialisation
  réelle (pas d'entrelacement) — rouge→vert vérifié par `git stash`. Les 8 tests existants adaptés en
  `async def` + `await`.

**Symptôme** : la fonction est correctement atomique (`mkstemp` même dossier + `chmod 600` + `os.replace`)
— aucun défaut de ce côté. Mais elle lit puis réécrit le fichier entier ; deux mises à jour concurrentes
de clés distinctes peuvent se perdre mutuellement (dernier `os.replace` gagne).

**Correction** : sérialiser les mises à jour `.env` (verrou) si plusieurs chemins d'admin peuvent y
écrire.
