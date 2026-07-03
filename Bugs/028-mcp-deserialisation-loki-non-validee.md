# 028 — MCP : désérialisation non validée de la réponse Loki

- **Sévérité** : mineur
- **Sous-système** : mcp / logs
- **Fichier** : `mcp/devpod_tools/logs_tools.py:72-74`
- **Statut** : ouvert

**Symptôme** :
```python
ts_ns_str, line = entry[0], entry[1]
ts_ms = int(ts_ns_str) // 1_000_000
```
Si Loki renvoie une entrée d'une autre forme (`entry` non-liste à 2 éléments, timestamp non numérique),
`IndexError`/`ValueError` non rattrapé — non couvert par les `except httpx.*`. Même conséquence que
[017](017-mcp-exceptions-non-gerees-echappent-dispatch.md) : exception brute + trou d'audit.

**Correction** : valider la structure (`_flatten_streams` défensif) ou envelopper `r.json()` + flatten
dans un `try` remontant un `DevpodToolError`.
