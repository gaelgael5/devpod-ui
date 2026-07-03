# 037 — Port `_reserved` jamais libéré sur échec synchrone de `up()`

- **Sévérité** : mineur
- **Sous-système** : devpod / exposure
- **Fichiers** : `devpod/service.py:198` (`allocate_port`), `finally` ~292-295 (ne libère pas), `exposure/ports.py:44` (`self._reserved.add(port)`)
- **Statut** : ouvert

**Symptôme** : si `_write_devcontainer` ou `ensure_provider` lève **après** l'allocation, la tâche n'est
pas créée, `up()` propage l'exception, mais le port reste dans `PortRegistry._reserved` sans jamais être
écrit en DB ni relâché → fuite d'un port de la plage 40000-49999 par échec, jusqu'au restart. Idem sur
le chemin `failed` de `_run_up_task`.

**Correction** : exposer `PortRegistry.release(port)` et l'appeler dans le `finally` de `up()` quand
`task_created is False`, et sur les branches d'échec de `_run_up_task`.

**Note** : distinct de [001](001-collision-allocation-ports-openvscode.md) (chemin d'exception synchrone,
pas restart / NULL).
