# Alerte « host injoignable » — sonde de vivacité (enabler 727ee81d)

## Ce que fait le portail

`backend/src/portal/nodes/liveness.py` : boucle de fond dédiée (démarrée au
lifespan quand `DATABASE_URL` est posé), **découplée du polling du front**.

- Check L4 léger : TCP connect sur le port de pilotage du host — port du daemon
  pour `docker-tls` (`tcp://ip:2376`), 22 pour `ssh`. Aucun SSH éphémère.
- Intervalle : `HOST_LIVENESS_INTERVAL_S` (défaut **15 s**).
- Hystérésis : bascule `unreachable` après `HOST_LIVENESS_FAILURES` échecs
  consécutifs (défaut **3**) ; retour `reachable` à la première réussite.
  Un hoquet d'un tick ne déclenche donc rien.
- Persistance : table `host_health` (migration 079) — alimente
  `node_list` (`health.reachable`, `health.last_seen`).
- Les hosts `usage=tests` (VM éphémères) ne sont **pas** sondés.

Sur **transition uniquement** (jamais à chaque tick), le portail émet la ligne
de log structurée :

```
host_reachability_changed host=<name> state=unreachable consecutive_failures=3   (niveau warning)
host_reachability_changed host=<name> state=reachable                            (niveau info)
```

## Règle d'alerte Grafana (à poser sur la stack existante)

Le contact point existe déjà — il n'y a qu'une règle à créer, branchée sur les
logs du portail dans Loki.

- **Requête (Loki)** :

  ```logql
  sum by (host) (
    count_over_time(
      {compose_service="portal"}
        | json
        | event = "host_reachability_changed"
        | state = "unreachable" [2m]
    )
  )
  ```

- **Condition** : `> 0` — le log n'est émis que sur transition, la fenêtre 2 min
  n'accumule donc pas de bruit.
- **Évaluation** : toutes les 30 s, pending period `0s` (la débounce est déjà
  faite par l'hystérésis côté portail).
- **Résolution auto** : la même requête avec `state = "reachable"` peut servir
  de règle de rétablissement, ou laisser l'alerte se résoudre quand la condition
  repasse à 0 après la fenêtre.
- **Notification** : contact point existant.
- **Libellé suggéré** : `Host {{ $labels.host }} injoignable (sonde portail)`.

Budget temps : 3 × 15 s de sonde + évaluation 30 s → alerte **< 1 minute** après
la disparition du host (critère du ticket).

## Même chaîne : alerte « workspace inactif » (enabler 6016436b)

La passe d'inactivité (`sessions/idle.py`, toutes les 5 min) émet — une seule
fois par période d'inactivité continue — la ligne :

```
workspace_idle_detected ws_id=<login-name> login=<login> idle_since=<iso> idle_hours=<n>
```

Règle Grafana optionnelle (l'UI porte déjà la suggestion avec bouton stop) :

```logql
{compose_service="portal"} | json | event = "workspace_idle_detected" [10m]
```

Condition `count > 0`, éval 5 min, contact point existant. **Aucune action
automatique** : l'alerte propose, l'humain arrête depuis le portail.

## Vérification (sur l'infra réelle)

1. Couper un host de test (ou bloquer son port 2376/22).
2. Attendre ~45 s : `node_list` doit montrer `reachable=false`, le log
   `host_reachability_changed state=unreachable` doit être dans Loki.
3. L'alerte doit parvenir via le contact point en < 1 min.
4. Rétablir : `state=reachable` au premier tick réussi, `last_seen` repart.
