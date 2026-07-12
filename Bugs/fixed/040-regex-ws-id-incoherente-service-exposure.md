# 040 — Incohérence des regex de validation `ws_id` entre service et exposure

- **Sévérité** : mineur (workspace running mais inaccessible, sans erreur visible)
- **Sous-système** : devpod / exposure
- **Fichiers** : `devpod/service.py:73` (`^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$` — long. ≤ 63, pas de point) vs `exposure/__init__.py:17` (`^[a-z0-9][a-z0-9._-]{0,38}[a-z0-9]$` — long. ≤ 40)
- **Statut** : corrigé — une seule `_WS_ID_RE` désormais, définie dans `exposure/__init__.py`
  (`^[a-z0-9][a-z0-9._-]{0,58}[a-z0-9]$`, max 60 chars) et importée par `devpod/service.py` (plus
  de duplication possible). Borne choisie : login (≤40, points autorisés) + "-" + name (≤32) peut
  atteindre 73 caractères bruts, mais le sous-domaine Caddy réel est `ws-{ws_id}` — un label DNS
  (RFC 1035) est limité à 63 caractères, donc ws_id plafonné à 60 pour laisser la place au préfixe
  `ws-`. `_ws_id()` rejette maintenant ce cas dès la construction. Tests ajoutés : même objet regex
  des deux côtés, combo login+name trop long rejeté tôt, ws_id dans la limite accepté par les deux,
  login avec point (LDAP) accepté par les deux (l'ancienne regex de service.py le rejetait) —
  rouge→vert vérifié par `git stash`.

**Symptôme** : un `ws_id` long (login long + name jusqu'à 32) passe `_ws_id()` (≤ 63) et provisionne, mais
`expose()` lève `ValueError("Invalid ws_id")`, attrapé comme `workspace_expose_failed`. Statut `running`
écrit **sans URL ni route Caddy** → le workspace tourne mais est inaccessible, sans erreur côté utilisateur.

**Correction** : aligner les deux regex (même longueur max, même jeu de caractères) et valider la longueur
du `ws_id` au plus tôt (dans `_ws_id`).

**Vérifié** : les deux regex confirmées par `grep` — bornes `{0,61}` vs `{0,38}` et jeu de caractères
différent (point autorisé côté exposure seulement).
