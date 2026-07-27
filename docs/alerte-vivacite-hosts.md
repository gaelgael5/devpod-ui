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

## Règle d'alerte Grafana — provisionnée avec la stack

**Rien à cliquer** : la règle est livrée en provisioning as-code dans
`deploy/grafana-provisioning/alerting/portal-alerts.yaml` (le compose dev ET
prod montent ce répertoire) — elle apparaît dans Grafana au prochain (re)démarrage
du conteneur grafana, branchée sur la politique de notification par défaut
→ contact point existant.

⚠️ Les logs du portail sont au format **console structlog, pas JSON** (Loki les
marque `JSONParserErr` si on tente `| json`) : la requête utilise des filtres de
ligne, robustes au format :

```logql
sum(count_over_time(
  {compose_service="portal"}
    |= `host_reachability_changed`
    |= `state=unreachable` [3m]
))
```

- **Condition** : `> 0` — le log n'est émis que sur transition, la fenêtre
  n'accumule donc pas de bruit.
- **Évaluation** : toutes les 30 s, pending `0s` (la débounce est déjà faite par
  l'hystérésis côté portail).
- **Notification** : politique par défaut → contact point existant.

Budget temps : 3 × 15 s de sonde + évaluation 30 s → alerte **< 1 minute** après
la disparition du host (critère du ticket).

## Même chaîne : alerte « workspace inactif » (enabler 6016436b)

La passe d'inactivité (`sessions/idle.py`, toutes les 5 min) émet — une seule
fois par période d'inactivité continue — la ligne :

```
workspace_idle_detected ws_id=<login-name> login=<login> idle_since=<iso> idle_hours=<n>
```

Règle **provisionnée elle aussi** (`portal-alerts.yaml`, groupe
`portal-workspaces`) — filtre de ligne `|= workspace_idle_detected`, fenêtre
10 min, éval 1 min, sévérité warning. **Aucune action automatique** : l'alerte
propose, l'humain arrête depuis le portail.

## Vérification (sur l'infra réelle)

1. Couper un host de test (ou bloquer son port 2376/22).
2. Attendre ~45 s : `node_list` doit montrer `reachable=false`, le log
   `host_reachability_changed state=unreachable` doit être dans Loki.
3. L'alerte doit parvenir via le contact point en < 1 min.
4. Rétablir : `state=reachable` au premier tick réussi, `last_seen` repart.
