# 025 — MCP : I/O fichier synchrone bloquant dans des handlers async

- **Sévérité** : mineur (viole « jamais d'I/O bloquant dans un handler »)
- **Sous-système** : mcp
- **Fichier** : `mcp/devpod_tools/operations.py:73-101` (`get_operation`, `list_operations`, `_write_atomic`, `update_operation`)
- **Statut** : ouvert

**Symptôme** : `_operations_list` appelle `list_operations` qui fait `glob("*.yaml")` puis, pour chaque
fichier, `read_text()` + `yaml.safe_load()` **synchrones dans l'event loop**, sans `asyncio.to_thread`.
Le coût croît avec le nombre d'opérations et gèle la boucle. `_workspace_logs`, lui, utilise bien
`asyncio.to_thread`.

**Correction** : déporter lectures/écritures YAML via `asyncio.to_thread`.
