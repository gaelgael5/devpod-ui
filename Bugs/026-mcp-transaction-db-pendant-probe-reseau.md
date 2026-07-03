# 026 — MCP : transaction DB maintenue ouverte pendant l'I/O réseau du probe

- **Sévérité** : mineur (contention du pool de connexions)
- **Sous-système** : mcp
- **Fichier** : `mcp/monitor.py:138` + `104-107` ; `routes/mcp.py:101`
- **Statut** : ouvert

**Symptôme** : `run_monitor_pass` enveloppe `monitor_backend_once` dans
`async with _get_engine().begin() as conn:`. Pour un backend externe, l'I/O réseau (`open_session`,
`list_tools`, `sync_backend`) se fait **dans** la transaction, jusqu'à `_PROBE_TIMEOUT_S = 60s`. Une
connexion du pool reste réservée pendant tout le round-trip. Combiné à `/mcp/backends/{id}/probe`,
plusieurs probes lents contendent le pool ; deux `sync_backend` concurrents sur le même backend
peuvent se bloquer sur les lignes du catalogue.

**Correction** : sortir l'I/O réseau de la transaction — probe réseau d'abord, puis courte transaction
pour l'upsert du catalogue.
