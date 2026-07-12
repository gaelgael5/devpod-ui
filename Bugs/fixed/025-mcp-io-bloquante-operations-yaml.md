# 025 — MCP : I/O fichier synchrone bloquant dans des handlers async

- **Sévérité** : mineur (viole « jamais d'I/O bloquant dans un handler »)
- **Sous-système** : mcp
- **Fichier** : `mcp/devpod_tools/operations.py:73-101` (`get_operation`, `list_operations`, `_write_atomic`, `update_operation`)
- **Statut** : corrigé — `create_operation`, `get_operation`, `update_operation`,
  `list_operations`, `launch_operation` sont désormais `async` et déportent
  glob/read_text/yaml.safe_load/`_write_atomic` via `asyncio.to_thread` (mêmes fonctions, logique
  sync isolée dans `_get_operation_sync`/`_list_operations_sync`). Tous les appelants dans
  `devpod_tools/__init__.py` (`_workspace_stop/reconnect/restart/create/delete/apply_recipe/
  profile_set`, `_operations_get`, `_operations_list`) `await` désormais ces appels ; les tests
  existants (`test_devpod_operations.py`, `test_devpod_lifecycle.py`,
  `test_devpod_async_lifecycle.py`) ont été mis à jour en conséquence (fixtures `fake_launch`
  devenues `async def`). Test ajouté prouvant la déportation effective : spy sur
  `asyncio.to_thread` qui capture les fonctions passées (`_write_atomic`, `_get_operation_sync`,
  `_list_operations_sync`) — rouge→vert vérifié par `git stash`.

**Symptôme** : `_operations_list` appelle `list_operations` qui fait `glob("*.yaml")` puis, pour chaque
fichier, `read_text()` + `yaml.safe_load()` **synchrones dans l'event loop**, sans `asyncio.to_thread`.
Le coût croît avec le nombre d'opérations et gèle la boucle. `_workspace_logs`, lui, utilise bien
`asyncio.to_thread`.

**Correction** : déporter lectures/écritures YAML via `asyncio.to_thread`.
