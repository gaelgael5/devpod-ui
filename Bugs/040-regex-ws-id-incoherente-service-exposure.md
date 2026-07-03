# 040 — Incohérence des regex de validation `ws_id` entre service et exposure

- **Sévérité** : mineur (workspace running mais inaccessible, sans erreur visible)
- **Sous-système** : devpod / exposure
- **Fichiers** : `devpod/service.py:73` (`^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$` — long. ≤ 63, pas de point) vs `exposure/__init__.py:17` (`^[a-z0-9][a-z0-9._-]{0,38}[a-z0-9]$` — long. ≤ 40)
- **Statut** : ouvert

**Symptôme** : un `ws_id` long (login long + name jusqu'à 32) passe `_ws_id()` (≤ 63) et provisionne, mais
`expose()` lève `ValueError("Invalid ws_id")`, attrapé comme `workspace_expose_failed`. Statut `running`
écrit **sans URL ni route Caddy** → le workspace tourne mais est inaccessible, sans erreur côté utilisateur.

**Correction** : aligner les deux regex (même longueur max, même jeu de caractères) et valider la longueur
du `ws_id` au plus tôt (dans `_ws_id`).

**Vérifié** : les deux regex confirmées par `grep` — bornes `{0,61}` vs `{0,38}` et jeu de caractères
différent (point autorisé côté exposure seulement).
