# 016 — Streaming SSH : sous-processus ssh non tué à la déconnexion client → déploiement orphelin

- **Sévérité** : majeur (fuite de process + conteneurs sans ligne DB)
- **Sous-système** : compose / host_exec
- **Fichiers** : `backend/src/portal/devpod/host_exec.py:101-141` (`stream_host_command`) ; consommé par `compose/service.py:325`, `routes/compose.py:296-316`
- **Statut** : ouvert

## Symptôme

Si le client HTTP se déconnecte pendant le streaming d'un `docker compose up`, le process ssh
continue sur le nœud (conteneurs démarrés, ports occupés), mais `create_deployment` n'est **jamais**
atteint → **aucune ligne DB** : déploiement fantôme + fuite de sous-processus.

## Cause racine

`stream_host_command` n'a **pas de `finally`** pour tuer le process ssh. Le `try/except HostExecError`
ne capture pas `GeneratorExit` (c'est une `BaseException`, pas une `Exception`). À la déconnexion,
Starlette lève `GeneratorExit` dans le générateur au point du `yield` → il meurt sans tuer le process.

Incohérence interne : `proxmox._ssh_stream` gère correctement ce cas (`except BaseException` +
`finally`) — c'est `stream_host_command` qui est l'exception.

## Piste de correction

Envelopper la boucle dans `try/.../finally` qui tue et attend le process (`proc.kill()` +
`await proc.wait()`), comme `_ssh_stream`. En complément : persister l'enregistrement du déploiement
(ligne « created ») **avant** le stream, pour ne jamais laisser de conteneurs sans trace DB.
