# 039 — I/O bloquante synchrone dans des handlers async (génération devcontainer)

- **Sévérité** : mineur (viole « jamais d'I/O bloquant dans un handler »)
- **Sous-système** : devpod
- **Fichiers** : `devpod/service.py:208` → `_write_devcontainer` (~500-612 : `mkdtemp`, `shutil.copytree`, `write_text` synchrones) ; `routes/workspace_ops.py:551` (`pub_path.read_text` synchrone)
- **Statut** : corrigé — `up()` appelle désormais `_write_devcontainer` via `asyncio.to_thread`
  (mkdtemp/copytree/write_text bloquants). `get_workspace_ssh_key` route `exists()`/`read_text()`
  via une nouvelle fonction `_read_ssh_public_key` appelée elle aussi via `asyncio.to_thread`.
  **Piège rencontré et corrigé pendant l'implémentation** : la première passe d'édition a laissé
  `_read_ssh_public_key` s'intercaler entre le décorateur `@router.get(...)` et
  `async def get_workspace_ssh_key`, déplaçant silencieusement la route sur la mauvaise fonction
  (404/200 attendus devenaient 422) — détecté par la suite de tests existante et corrigé avant
  commit. Tests ajoutés (spy sur `asyncio.to_thread`) : `up()` déporte bien `_write_devcontainer`,
  `get_workspace_ssh_key` déporte bien `_read_ssh_public_key` — rouge→vert vérifié par `git stash`.

**Symptôme** : `copytree` de plusieurs répertoires de recettes bloque l'event loop pendant tout le
provisioning, stallant les autres requêtes. `read_text` de la clé publique bloque aussi (marginal).

**Correction** : envelopper la génération devcontainer dans `asyncio.to_thread` (comme c'est déjà fait
pour les logs en `workspace_ops.py:678`).
