# 012 — Comparaison non constant-time de `portal_api_key` (bearer admin)

- **Sévérité** : majeur
- **Sous-système** : auth
- **Fichier** : `backend/src/portal/auth/rbac.py:102`
- **Statut** : ouvert

## Symptôme

Fuite temporelle byte-par-byte permettant de deviner la clé admin statique par attaque de timing.

## Cause racine

```python
if settings.portal_api_key and credentials.credentials == settings.portal_api_key:
    return UserInfo(login="__api__", roles=[settings.oidc_admin_role])
```

`==` Python court-circuite au premier octet divergent. Ce token est une clé admin **longue durée et
statique** (haute valeur). Incohérence : le reste du code utilise déjà `hmac.compare_digest`
(ex. `oauth/pkce.py:21`), donc ce n'est pas une contrainte technique.

## Piste de correction

`hmac.compare_digest(credentials.credentials, settings.portal_api_key)` après avoir vérifié que
`portal_api_key` est non vide.
