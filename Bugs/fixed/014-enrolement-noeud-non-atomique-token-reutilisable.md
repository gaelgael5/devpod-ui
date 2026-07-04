# 014 — Enrôlement de nœud non atomique → join token réutilisable + état incohérent

- **Sévérité** : majeur
- **Sous-système** : nodes
- **Fichiers** : `backend/src/portal/nodes/enroll.py:153-207` (`enroll_node`), couplé à `config/store.py:98-103` (`save_global` ouvre sa propre transaction)
- **Statut** : corrigé — `enroll_node` écrit désormais consommation du token, enregistrement du
  host (via `save_global_db(conn)` au lieu de `save_global`, qui ouvrait sa propre transaction) et
  ligne de certificat sur **une seule** `conn` : elles committent/rollbackent ensemble. La route
  `/nodes/enroll` ouvre elle-même la transaction (au lieu de `Depends(get_conn)`) et ne rafraîchit
  le cache RAM qu'après un COMMIT réussi (bug 034). Sur rollback, le token n'est jamais réutilisable
  pendant qu'un host reste enregistré. Compromis écriture disque du cert : le fichier est écrit en
  **dernier** (après les écritures DB), via `os.replace` atomique et idempotent ; seul un échec du
  COMMIT final peut laisser un cert orphelin, inoffensif (aucune ligne host committée ne le référence,
  inutilisable seul) et écrasé à l'identique au prochain essai — moindre mal qu'un token rejouable.
  Renfort ajouté à la relecture : `enroll_node` fait un `cfg.model_copy(deep=True)` avant d'ajouter
  le host, car `load_global()` renvoie l'objet caché **vivant** (`get_cached_global`) — muter
  `cfg.hosts` en place polluerait le cache RAM avant le COMMIT et le laisserait pollué sur rollback
  (host fantôme). Le cache n'est donc rafraîchi que par la route, après COMMIT, via `set_cached_global`
  (cohérent bug 034). Test `test_enroll_node_does_not_mutate_live_cache_before_commit` (rouge→vert).

## Symptôme

Après un échec en fin d'enrôlement, le join token — censé usage unique — redevient **valide dans sa
TTL**, alors que le host est déjà enregistré et le cert écrit sur disque sans ligne
`node_certificates`. Split-brain.

## Cause racine

`enroll_node` reçoit une `conn` (transaction de requête, commitée en toute fin). Elle :
1. `consume_token_db(conn)` marque `used=True` dans la **transaction externe non commitée** ;
2. écrit le cert sur disque ;
3. appelle `_register_host` → `save_global` qui **ouvre sa propre transaction** (`_get_engine().begin()`)
   et **commit immédiatement** ;
4. `save_node_cert_db(conn)` sur la transaction externe.

Si l'étape 4 ou le commit final échoue (erreur DB, client déconnecté), la transaction externe
**rollback** → le flag `used` du token repasse à `False`, alors que le host (étape 3) est déjà
committé et le cert sur disque. La garantie d'usage unique (correcte dans `db/tokens.py`) est annulée
par cette rupture d'atomicité.

## Piste de correction

Faire écrire `_register_host` / `save_global_db` sur la **même** `conn` que le reste de l'enrôlement,
pour que consommation du token + enregistrement du host + persistance du cert soient dans une seule
transaction (tout ou rien).
