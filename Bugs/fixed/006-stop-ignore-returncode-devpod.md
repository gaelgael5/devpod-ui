# 006 — `stop()` écrit le statut « stopped » même si `devpod stop` a échoué

- **Sévérité** : majeur
- **Sous-système** : devpod
- **Fichier** : `backend/src/portal/devpod/service.py` — `stop()` (~418-427)
- **Statut** : corrigé — `stop()` capture désormais le `returncode`, écrit `unknown` (pas `stopped`) en cas d'échec. Tests ajoutés (`tests/devpod/test_stop.py`, round-trip DB : succès + échec).

## Symptôme

Un `stop` sur un daemon injoignable (ou timeout partiel) détruit l'exposition (route Caddy +
port-forward) **avant** de tenter l'arrêt, puis marque le workspace `stopped` alors que le conteneur
tourne toujours. L'UI affiche `stopped`, le conteneur consomme des ressources, et le workspace est
devenu inaccessible (exposition détruite) sans moyen de le « réveiller » autrement qu'en relançant
un `up`.

## Cause racine

```python
await self._stop_port_forward(ws_id)          # exposition retirée d'abord
...
await run_subprocess(cmd=cmd, ...)             # returncode NON capturé
...
await self._write_status(ws_id, "stopped", login=login)   # écrit inconditionnellement
```

Le `returncode` de `run_subprocess` est ignoré. Asymétrie flagrante : `delete()` teste bien son
returncode, `stop()` non.

## Piste de correction

Capturer `rc = await run_subprocess(...)`. Si `rc != 0`, logguer et écrire un statut `error`/`unknown`
au lieu de `stopped` (ou ne retirer l'exposition qu'après confirmation de l'arrêt). Idéalement sous
le verrou lifecycle de [003](003-absence-verrou-lifecycle-workspace.md).

## Vérifié

Confirmé par lecture directe de `stop()` : `run_subprocess` est awaité sans capture du retour, puis
`_write_status(ws_id, "stopped")` inconditionnel.
