# 036 — `reconcile_port_forwards` : `create_task` fire-and-forget non référencé (GC possible)

- **Sévérité** : mineur
- **Sous-système** : devpod
- **Fichier** : `backend/src/portal/devpod/service.py:359` (`asyncio.create_task(self._reconnect_workspace(...))` — pas de stockage, pas de `# noqa: RUF006`, contrairement à la ligne 416)
- **Statut** : ouvert

**Symptôme** : au démarrage, si l'état devpod est manquant pour plusieurs workspaces, les tâches de
reconnexion ne sont référencées nulle part ; le GC peut les collecter **en cours d'exécution**
(comportement documenté d'`asyncio`), interrompant silencieusement la reconnexion.

**Correction** : stocker la task dans `self._background_tasks` avec `add_done_callback(discard)`, comme
le fait `up()`.

**Vérifié** : ligne 359 sans stockage ni `# noqa` ; la ligne 416 (`reconnect()`) a bien le `# noqa: RUF006`.
