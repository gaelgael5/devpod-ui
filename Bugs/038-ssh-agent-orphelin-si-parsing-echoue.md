# 038 — Fuite de process `ssh-agent` si le parsing de sa sortie échoue

- **Sévérité** : mineur (chemin d'erreur rare)
- **Sous-système** : devpod
- **Fichier** : `devpod/service.py:840-869` (setup) / `963-972` (cleanup conditionné à `agent_pid`)
- **Statut** : ouvert

**Symptôme** : `ssh-agent -s` est lancé ; si `sock_match`/`pid_match` ne matchent pas, `agent_pid` reste
`None`, donc le `finally` ne tue jamais l'agent → process `ssh-agent` orphelin par occurrence.

**Cause** : le PID n'est capturé qu'après un parsing regex qui peut échouer, alors que le process est
déjà lancé.

**Correction** : conserver le handle `agent_proc` dès le lancement et le tuer dans le `finally`
indépendamment du succès du parsing.
