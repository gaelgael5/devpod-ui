# 039 — I/O bloquante synchrone dans des handlers async (génération devcontainer)

- **Sévérité** : mineur (viole « jamais d'I/O bloquant dans un handler »)
- **Sous-système** : devpod
- **Fichiers** : `devpod/service.py:208` → `_write_devcontainer` (~500-612 : `mkdtemp`, `shutil.copytree`, `write_text` synchrones) ; `routes/workspace_ops.py:551` (`pub_path.read_text` synchrone)
- **Statut** : ouvert

**Symptôme** : `copytree` de plusieurs répertoires de recettes bloque l'event loop pendant tout le
provisioning, stallant les autres requêtes. `read_text` de la clé publique bloque aussi (marginal).

**Correction** : envelopper la génération devcontainer dans `asyncio.to_thread` (comme c'est déjà fait
pour les logs en `workspace_ops.py:678`).
