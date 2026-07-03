# TODO — dette et chantiers identifiés

## Bugs

- [ ] **Allocation des ports openvscode : collisions entre workspaces** (identifié le 2026-07-03
  pendant le debug « Open VS Code »). `PortRegistry.allocate()` s'appuie sur les `host_port`
  persistés en DB + un set `_reserved` en mémoire. Deux failles :
  1. `_write_status(ws_id, "provisioning")` remet `host_port` à NULL pendant toute la durée du
     `devpod up` (jusqu'à 30 min) → le port de l'ancien tunnel encore actif redevient « libre »
     pour un up concurrent d'un autre workspace ;
  2. `_reserved` est perdu à chaque redémarrage du portail, et la réconciliation au démarrage
     déclenche des `devpod up` concurrents → réallocations en rafale.
  Conséquence observée sur dev.yoops.org : `admin-rag` et `admin-devpod` persistés tous les deux
  avec `host_port=40000`. Depuis `4c7dfdc` un conflit de bind est au moins **bruyant**
  (`ExitOnForwardFailure=yes` → `port_forward_died` dans les logs) au lieu d'un proxy qui sert le
  mauvais workspace, mais la cause structurelle reste à traiter : préserver `host_port` pendant le
  provisioning (ou réserver le port en DB), et réutiliser le port existant d'un workspace lors
  d'un re-up au lieu d'en réallouer un.
