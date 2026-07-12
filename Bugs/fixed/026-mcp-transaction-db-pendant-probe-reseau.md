# 026 — MCP : transaction DB maintenue ouverte pendant l'I/O réseau du probe

- **Sévérité** : mineur (contention du pool de connexions)
- **Sous-système** : mcp
- **Fichier** : `mcp/monitor.py:138` + `104-107` ; `routes/mcp.py:101`
- **Statut** : corrigé — `monitor_backend_once` accepte désormais `conn: AsyncConnection | None`.
  Quand `conn` est fourni (route `/probe`, tests existants), le comportement est strictement
  inchangé (même connexion réutilisée tout du long). Quand `conn` est `None` (nouveau mode utilisé
  par `run_monitor_pass`), les connexions sont acquises au fil de l'eau : une connexion courte pour
  résoudre le bearer, **relâchée avant** le round-trip réseau (`open_session` + nouvelle fonction
  `catalog.fetch_backend_catalog`, réseau seul), puis une transaction courte dédiée
  (`catalog.write_backend_catalog`, DB seule) ouverte **après** que le réseau a terminé.
  `run_monitor_pass` ne tient donc plus aucune connexion pendant les 60s potentielles du timeout de
  probe. `sync_backend` conservé tel quel (combine les deux phases dans un seul `conn`, pour l'usage
  route/tests à connexion unique). Test ajouté (mocks purs, sans Docker) qui vérifie l'ordre exact
  des acquisitions de connexion : `connect→bearer, réseau, begin→écriture` — rouge→vert vérifié par
  `git stash`. Suite complète : 883 passés (+1), 171 échecs pré-existants identiques.

**Symptôme** : `run_monitor_pass` enveloppe `monitor_backend_once` dans
`async with _get_engine().begin() as conn:`. Pour un backend externe, l'I/O réseau (`open_session`,
`list_tools`, `sync_backend`) se fait **dans** la transaction, jusqu'à `_PROBE_TIMEOUT_S = 60s`. Une
connexion du pool reste réservée pendant tout le round-trip. Combiné à `/mcp/backends/{id}/probe`,
plusieurs probes lents contendent le pool ; deux `sync_backend` concurrents sur le même backend
peuvent se bloquer sur les lignes du catalogue.

**Correction** : sortir l'I/O réseau de la transaction — probe réseau d'abord, puis courte transaction
pour l'upsert du catalogue.
