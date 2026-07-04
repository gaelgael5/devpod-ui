# 038 — Fuite de process `ssh-agent` si le parsing de sa sortie échoue

- **Sévérité** : mineur (chemin d'erreur rare)
- **Sous-système** : devpod
- **Fichier** : `devpod/service.py:840-869` (setup) / `963-972` (cleanup conditionné à `agent_pid`)
- **Statut** : corrigé — **vérifié empiriquement** que `ssh-agent -s` seul daemonise : le process
  lancé imprime les variables d'env puis sort immédiatement, le vrai agent tournant en arrière-plan
  sous un **PID différent**, jamais capturé (donc « garder le handle » seul, comme suggéré
  initialement, n'aurait rien changé). Le fix ajoute `-D` (foreground) : `agent_proc` reste le
  process réel tout du long, `agent_proc.pid` est le vrai PID, tué directement dans le `finally`
  (`agent_proc.kill()` + `wait()`) indépendamment du succès du parsing de `SSH_AUTH_SOCK` sur sa
  sortie. `SSH_AGENT_PID` n'a plus besoin d'être parsé : `agent_proc.pid` le fournit directement.
  Tests ajoutés (vrai binaire `ssh-agent`, pas de mock) : caractérisation du bug (sans `-D`, PID du
  lanceur ≠ PID de l'agent réel), le fix (`-D` → PID réel, tuable), et le cas précis du bug (tuable
  même si la sortie est ignorée/imparsable).

**Symptôme** : `ssh-agent -s` est lancé ; si `sock_match`/`pid_match` ne matchent pas, `agent_pid` reste
`None`, donc le `finally` ne tue jamais l'agent → process `ssh-agent` orphelin par occurrence.

**Cause** : le PID n'est capturé qu'après un parsing regex qui peut échouer, alors que le process est
déjà lancé.

**Correction** : conserver le handle `agent_proc` dès le lancement et le tuer dans le `finally`
indépendamment du succès du parsing.
