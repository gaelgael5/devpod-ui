# 028 — MCP : désérialisation non validée de la réponse Loki

- **Sévérité** : mineur
- **Sous-système** : mcp / logs
- **Fichier** : `mcp/devpod_tools/logs_tools.py:72-74`
- **Statut** : corrigé — `_flatten_streams` valide désormais la forme de la réponse (`data` non-dict
  → liste vide, `data.result` non-liste, `stream` non-dict, entrée qui n'est pas une paire
  `[ts, line]`, timestamp non numérique) et lève `DevpodToolError` au lieu d'un
  IndexError/ValueError/AttributeError brut. `_logs_query` enveloppe aussi `r.json()` pour
  transformer un corps non-JSON (`json.JSONDecodeError`) en `DevpodToolError`. Tests ajoutés (7,
  rouge→vert vérifié par `git stash`) : arité d'entrée invalide, timestamp non numérique, stream
  non-dict, `result` non-liste, `data` absent/non-dict (liste vide, pas de crash), corps non-JSON,
  et le chemin complet `_logs_query` avec une réponse Loki 200 mais structurellement invalide.

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
