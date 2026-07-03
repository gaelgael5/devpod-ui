# 015 — Course sur l'allocation de ports compose (deux déploiements → même port)

- **Sévérité** : majeur
- **Sous-système** : compose
- **Fichiers** : `backend/src/portal/compose/ports.py:42-65` (`allocate_ports`), `compose/service.py:246-349`, `routes/compose.py:261-316`
- **Statut** : ouvert

## Symptôme

Deux déploiements compose concurrents sur le même nœud reçoivent le **même port hôte**, provoquant un
conflit de bind (ou deux services qui se disputent le port).

## Cause racine

En mode alias, `prepare_deployment` → `allocate_ports` calcule les ports à partir de
`used_ports_on_node` (lignes **commitées** en DB) + ports live (`ss -ltn`). Or la ligne du nouveau
déploiement (avec ses `host_ports`) n'est persistée qu'à la **toute fin** de `deploy_stream`
(`create_deployment`, transaction séparée, **après** `docker compose up`, jusqu'à 600 s plus tard).
Deux requêtes concurrentes lisent le même `used_ports_on_node` (aucune ne voit l'allocation de
l'autre, non encore persistée) → même port. Le garde-fou live (`ss`) ne rattrape le conflit que si le
premier `compose up` a déjà bindé le port.

## Piste de correction

Verrou consultatif Postgres (`pg_advisory_xact_lock` par `node_id`) autour de allocation+réservation,
**ou** insérer immédiatement une ligne de déploiement « created » réservant les ports **avant** de
lancer `compose up`.

## Note

Même famille de défaut que [001](001-collision-allocation-ports-openvscode.md) (allocation de ports
openvscode) : la réservation n'est pas durable pendant la fenêtre de provisioning.
