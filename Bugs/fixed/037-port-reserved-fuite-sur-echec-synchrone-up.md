# 037 — Port `_reserved` jamais libéré sur échec synchrone de `up()`

- **Sévérité** : mineur
- **Sous-système** : devpod / exposure
- **Fichiers** : `devpod/service.py:198` (`allocate_port`), `finally` ~292-295 (ne libère pas), `exposure/ports.py:44` (`self._reserved.add(port)`)
- **Statut** : corrigé — `PortRegistry.release(port)` (nouveau) libère un port de `_reserved` ;
  `ExposureService.release_port(port)` délègue. `up()` appelle `release_port` dans son `finally`
  quand `task_created` est `False` et qu'un port avait été alloué (`host_port` hissé avant le `try`
  pour rester visible dans le `finally`). `_run_up_task` l'appelle aussi dans son
  `except Exception as exc:` (chemin de crash qui, contrairement au chemin `returncode != 0`,
  n'écrivait jamais `host_port` en DB). Tests ajoutés : `PortRegistry.release` retire bien le port
  (et no-op sur un port inconnu, sans DB requise), `ExposureService.release_port` délègue au
  registre, et un test bout-en-bout de `up()` (mock d'`ensure_provider`/`_write_devcontainer`
  forçant un échec synchrone après l'allocation) qui vérifie `release_port` est appelé — rouge→vert
  vérifié par `git stash`.

**Symptôme** : si `_write_devcontainer` ou `ensure_provider` lève **après** l'allocation, la tâche n'est
pas créée, `up()` propage l'exception, mais le port reste dans `PortRegistry._reserved` sans jamais être
écrit en DB ni relâché → fuite d'un port de la plage 40000-49999 par échec, jusqu'au restart. Idem sur
le chemin `failed` de `_run_up_task`.

**Correction** : exposer `PortRegistry.release(port)` et l'appeler dans le `finally` de `up()` quand
`task_created is False`, et sur les branches d'échec de `_run_up_task`.

**Note** : distinct de [001](001-collision-allocation-ports-openvscode.md) (chemin d'exception synchrone,
pas restart / NULL).
