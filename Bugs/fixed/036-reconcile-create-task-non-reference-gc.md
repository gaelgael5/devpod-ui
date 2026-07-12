# 036 — `reconcile_port_forwards` : `create_task` fire-and-forget non référencé (GC possible)

- **Sévérité** : mineur
- **Sous-système** : devpod
- **Fichier** : `backend/src/portal/devpod/service.py:359` (`asyncio.create_task(self._reconnect_workspace(...))` — pas de stockage, pas de `# noqa: RUF006`, contrairement à la ligne 416)
- **Statut** : corrigé — la task est désormais stockée dans `self._background_tasks` +
  `add_done_callback(discard)`, identique au motif déjà utilisé ailleurs dans le fichier (lignes
  267-288). `reconnect()` (ligne 418, déjà `# noqa: RUF006`) n'est pas concerné : suppression
  délibérée déjà documentée, hors périmètre de cette fiche. Test ajouté
  (`tests/devpod/test_reconcile.py`) : pendant que la task de reconnexion est suspendue en plein
  vol (contrôlée par un `asyncio.Event`), elle doit être présente dans `_background_tasks`, puis en
  être retirée une fois terminée — rouge→vert vérifié par `git stash`.

**Symptôme** : au démarrage, si l'état devpod est manquant pour plusieurs workspaces, les tâches de
reconnexion ne sont référencées nulle part ; le GC peut les collecter **en cours d'exécution**
(comportement documenté d'`asyncio`), interrompant silencieusement la reconnexion.

**Correction** : stocker la task dans `self._background_tasks` avec `add_done_callback(discard)`, comme
le fait `up()`.

**Vérifié** : ligne 359 sans stockage ni `# noqa` ; la ligne 416 (`reconnect()`) a bien le `# noqa: RUF006`.
