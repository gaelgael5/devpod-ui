# 002 — Fuite de secrets du portail via le résolveur `env://` dans un déploiement compose

- **Sévérité** : critique (escalade de privilèges : compte `dev` → KEK vault / secret de session / secret OIDC)
- **Sous-système** : secrets / compose
- **Fichiers** :
  - `backend/src/portal/secrets/resolver.py:24-46` (branche `env`)
  - `backend/src/portal/compose/service.py:42` (`_SECRET_REF_RE` autorise `env`), `~86-94` (`_validate_secret_refs`), `~155` (`resolve_env_values`)
  - `backend/src/portal/routes/compose.py` (`create_deployment`, `Depends(require_user)`)
  - `backend/src/portal/schemas/compose.py` (`env_values: dict[str, str]` non restreint)
- **Statut** : ouvert

## Symptôme

Un utilisateur au simple rôle `dev` peut lire **n'importe quelle variable d'environnement du
process portail** — dont `PORTAL_VAULT_KEK`, `SESSION_SECRET_KEY`, `OIDC_CLIENT_SECRET`,
`DATABASE_URL`, `PORTAL_API_KEY`, `LOCAL_PASSWORD_HASH` — en la faisant écrire dans le `.env` d'un
conteneur compose qu'il déploie, puis en la lisant depuis son propre workspace.

## Scénario de déclenchement

`POST /compose/deployments` avec un `env_values` arbitraire :
```json
{ "name": "x", "template_id": "...", "node_id": "...",
  "env_values": { "LEAK": "${env://PORTAL_VAULT_KEK}" } }
```
1. `env_values` n'est jamais restreint aux paramètres déclarés du template : le schéma
   (`schemas/compose.py`) est un `dict[str,str]` libre, et `create_deployment` ne vérifie que la
   **présence** des paramètres `required`, pas l'inverse (aucune clé étrangère rejetée).
2. `deploy()` passe chaque valeur à `resolve()`. La valeur matche `^\$\{(vault|env)://(.+)\}$`,
   branche `env` → `os.environ.get("PORTAL_VAULT_KEK")` retourné en clair.
3. La valeur est écrite dans le `.env` du conteneur de l'utilisateur (`render_env_file`), qu'il lit
   ensuite dans son workspace.

Avec `SESSION_SECRET_KEY` récupéré, l'attaquant **forge des cookies de session signés valides**,
y compris avec le rôle `admin` → compromission totale du portail.

## Cause racine

`backend/src/portal/secrets/resolver.py` :
```python
if kind == "env":
    env_val = os.environ.get(path)          # aucun filtrage
    if env_val is None:
        raise SecretAccessError(...)
    return Secret(env_val)
```
La branche `env://` traite tout l'espace des variables d'environnement du process comme un magasin
de secrets utilisateur. L'isolation `secret_ns` soigneusement appliquée pour `vault://`
(`_validate_user_vault_path` : rejet `..`, namespace étranger, chemin absolu) est **totalement
contournée** par `env://`. Aggravant : `_validate_secret_refs` n'inspecte que les paramètres
`type == "secret"`, et même pour ceux-là `_SECRET_REF_RE` autorise explicitement `env`.

## Piste de correction

Défense en profondeur, plusieurs couches :
1. **Supprimer la branche `env://`** du résolveur exposé aux entrées utilisateur — ou la restreindre
   à une **allowlist** stricte de noms non sensibles (jamais `PORTAL_*`, `SESSION_*`, `OIDC_*`,
   `DATABASE_*`, `LOCAL_*`).
2. Retirer `env` de `_SECRET_REF_RE` dans `compose/service.py` (n'autoriser que `vault://` côté
   compose).
3. **Filtrer `env_values`** aux seuls `p.key` déclarés par le template **avant** résolution, et
   rejeter (422) toute clé étrangère.

## Vérifié

Confirmé par lecture directe : `resolver.py:33-37` fait bien `os.environ.get(path)` sans filtre ;
`compose/service.py:42` a `_SECRET_REF_RE = re.compile(r"^\$\{(vault|env)://.+\}$")` qui accepte `env`.
