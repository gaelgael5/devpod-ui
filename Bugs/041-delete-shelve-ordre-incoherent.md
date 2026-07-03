# 041 — `delete` propage le 409 de shelve après avoir déjà tué l'`up` en cours

- **Sévérité** : mineur
- **Sous-système** : devpod
- **Fichier** : `devpod/service.py:439` (`kill_if_running`), `444` (`shelve_if_pending` → peut lever `HTTPException(409)`, `shelve.py:85`), `445` (`_stop_port_forward`)
- **Statut** : ouvert

**Symptôme** : `delete` sur un workspace en cours de provisioning tue d'abord le subprocess `up`, puis
`shelve_if_pending` lance `devpod ssh` sur un conteneur à moitié provisionné → échec → 409 « suppression
annulée ». Résultat : l'`up` est mort, le workspace reste à moitié provisionné non nettoyé, et le
port-forward n'a pas été retiré (le `_stop_port_forward` est **après** le shelve).

**Correction** : ne tenter le shelve que si le workspace est réellement `running` (lire le statut avant),
ou déplacer `kill_if_running` après un shelve réussi ; encapsuler dans le verrou lifecycle de
[003](003-absence-verrou-lifecycle-workspace.md).
